"""Disposable gateway; only the IdP and loopback model wire are synthetic."""
import asyncio
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import traceback

from tests.gateway.fixtures.shared_authority_peer import ModelPeer
from tests.waiting import async_wait_until


async def probe(peer, creator):
    from websockets.asyncio.client import connect
    from gateway.run import GatewayRunner
    from gateway.run_bootstrap import _start_gateway_start_control_socket
    from gateway.run_runtime import (initialize_gateway_runtime, start_gateway_runtime_api,
                                     publish_gateway_runtime_ready)
    from gateway.runtime_ownership import process_ownership
    from hermes_state_local import local_receipt
    from hermes_state_runtime import list_session_admissions
    from tests.gateway.test_normal_runtime_boot import control

    home = Path(os.environ['HERMES_HOME'])
    process_ownership.reserve([home])
    runner = GatewayRunner()
    sockets = []
    bootstrap = None
    try:
        await initialize_gateway_runtime(runner)
        bootstrap = await _start_gateway_start_control_socket(runner)
        assert bootstrap is not None
        await start_gateway_runtime_api(runner)
        assert await runner.start()
        publish_gateway_runtime_ready(runner)
        descriptor = await asyncio.to_thread(control, home, 'identify')
        authority = runner.session_authority
        origin = descriptor['api_origin']
        url = origin.replace('http:', 'ws:') + '/api/ws'
        binding = dict(profile_id=str(home), instance_id=descriptor['instance_id'], purpose='interactive')

        async def native(purpose='interactive'):
            grant = await asyncio.to_thread(control, home, 'session-ticket', {**binding, 'purpose': purpose})
            ws = await connect(url, subprotocols=['hermes-gateway-v1', 'hermes-gateway-ticket.' + grant['ticket']])
            sockets.append(ws)
            return ws

        counter = 0
        async def rpc(ws, method, error=None, **params):
            nonlocal counter
            counter += 1
            rid = counter
            await ws.send(json.dumps(dict(jsonrpc='2.0', id=rid, method=method, params=params)))
            async with asyncio.timeout(20):
                while True:
                    frame = json.loads(await ws.recv())
                    if frame.get('id') == rid:
                        if error:
                            assert frame.get('error', {}).get('message') == error, frame
                            return frame['error']
                        assert 'result' in frame, frame
                        return frame['result']

        # Two local windows of the same owner: both hold native tickets and act as the machine
        # owner on one canonical session.
        owner, viewer = await native(), await native()
        created = await rpc(owner, 'session.create', request_id='cross-surface-create',
                            source=creator, cwd=str(home), toolsets=[])
        sid = created['session_id']
        assert created['stored_session_id'] == sid
        original_owner = local_receipt(authority.db, sid)['principal_id']
        initial = await rpc(owner, 'session.resume', session_id=sid)
        # Bounded, benign invalid requests: restricted bootstrap purpose is not an operator.
        restricted = await native('worker-adoption')
        await rpc(restricted, 'session.resume', error='permission_denied', session_id=sid)
        await rpc(restricted, 'prompt.submit', error='permission_denied', session_id=sid,
                  input_id='restricted', text='not admitted')
        for changed in ({'profile_id': str(home / 'other')}, {'instance_id': 'another-instance'}):
            try:
                await asyncio.to_thread(control, home, 'session-ticket', {**binding, **changed})
            except AssertionError as exc:
                assert 'PermissionError' in str(exc), str(exc)
            else:
                raise AssertionError('bootstrap accepted foreign binding')
        for field, value in (('operator', True), ('operator_scope', str(home)),
                             ('capabilities', ['session:operator'])):
            await rpc(viewer, 'session.create', error='invalid_params',
                      request_id='unsupported-' + field, source='gui', **{field: value})

        attached = await rpc(viewer, 'session.resume', session_id=sid)
        assert attached['stored_session_id'] == sid
        assert attached['replay_epoch'] == initial['replay_epoch']
        assert attached['subscription_id'] != initial['subscription_id']
        listing = await rpc(viewer, 'session.list')
        assert sid in {row['session_id'] for row in listing['sessions']}

        first = await rpc(owner, 'prompt.submit', session_id=sid, input_id='first',
                          text='BLOCK_FIFO WS_SHARED')
        assert first['status'] == 'queued', first
        assert await asyncio.to_thread(peer.blocked.wait, 25), 'real inference never started'
        followup = dict(session_id=sid, input_id='followup', text='WS_SHARED followup')
        accepted = await rpc(viewer, 'prompt.submit', **followup)
        assert accepted['status'] == 'queued', accepted
        assert await rpc(viewer, 'prompt.submit', **followup) == accepted
        rows = list_session_admissions(authority.db, session_id=sid, pending_only=False)
        assert len(rows) == 2, rows
        # Hermes is single-user: both local surfaces act as the machine owner, so their
        # admissions carry the owner's own OS subject and neither is an operator hand-off.
        assert rows[0]['principal_id'] == original_owner, rows
        assert rows[1]['principal_id'] == original_owner, rows
        assert all('local_operator_v1' not in row['payload'] for row in rows), rows
        attribution = [row['principal_id'] for row in rows]
        assert all(subject.startswith('uid:') for subject in attribution), attribution
        await owner.close()
        await viewer.close()
        # No connected viewer owns this accepted work. A new surface sees the same queue.
        viewer = await native()
        assert (await rpc(viewer, 'session.resume', session_id=sid))['stored_session_id'] == sid
        assert await rpc(viewer, 'prompt.submit', **followup) == accepted
        peer.release.set()
        def settled():
            rows = list_session_admissions(authority.db, session_id=sid, pending_only=False)
            return rows if len(rows) == 2 and all(row['status'] == 'terminal' for row in rows) else None
        rows = await async_wait_until(settled, timeout=45, what='both admissions terminal')
        assert [row['principal_id'] for row in rows] == attribution
        assert local_receipt(authority.db, sid)['principal_id'] == original_owner
        messages = authority.db.get_messages_as_conversation(sid)
        user_text = [m['content'] for m in messages if m['role'] == 'user']
        assert user_text == ['BLOCK_FIFO WS_SHARED', 'WS_SHARED followup'], messages
        assert len(peer.requests) == 2, peer.requests
        assert any(message['role'] == 'assistant' and 'LOCAL_ACK_WS_SHARED' in str(message['content'])
                   for message in peer.requests[1]['messages']), peer.requests[1]
        systems = [[message for message in request['messages'] if message['role'] == 'system']
                   for request in peer.requests]
        assert systems[0] == systems[1], 'operator handoff changed frozen system policy'
        assert 'local_operator_v1' not in json.dumps(peer.requests)
        replay = await rpc(viewer, 'session.events.since', session_id=sid,
                           replay_epoch=initial['replay_epoch'], last_sequence=initial['last_sequence'])
        assert not replay['snapshot_required'], replay
        assert len([event for event in replay['events'] if event['type'] == 'message.complete']) == 2
        snapshot = await rpc(viewer, 'session.resume', session_id=sid)
        assert snapshot['stored_session_id'] == sid
        assert 'LOCAL_ACK_WS_SHARED' in json.dumps(snapshot['messages'])
        assert 'local_operator_v1' not in json.dumps([initial, attached, accepted, replay, snapshot])
        (home / 'operator-receipt.json').write_text(json.dumps(dict(
            creator=creator, model_requests=len(peer.requests), owner_attribution=True,
            disconnect_survived=True, negative_boundaries=True)))
    finally:
        peer.release.set()
        for ws in sockets:
            await ws.close()
        if bootstrap:
            await bootstrap.stop()
        await runner.stop()
        process_ownership.close()


def main():
    peer = ThreadingHTTPServer(('127.0.0.1', 0), ModelPeer)
    peer.requests, peer.metadata_requests = [], []
    peer.blocked, peer.release = threading.Event(), threading.Event()
    thread = threading.Thread(target=peer.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{peer.server_port}/v1'
    os.environ.update(OPENAI_API_KEY='loopback-only', OPENAI_BASE_URL=url)
    home = Path(os.environ['HERMES_HOME'])
    (home / 'config.yaml').write_text(json.dumps({
        'gateway': {'multiplex_profiles': False},
        'model': {'provider': 'custom', 'default': 'local-wire-stub', 'base_url': url},
        'auxiliary': {'title_generation': {'enabled': False}},
    }))
    try:
        asyncio.run(probe(peer, sys.argv[1]))
    finally:
        peer.release.set()
        peer.shutdown()
        peer.server_close()
        thread.join(timeout=5)


if __name__ == '__main__':
    status = 0
    try:
        main()
    except BaseException:
        traceback.print_exc()
        status = 1
    # Third-party executor threads must not outlive this disposable test process.
    os._exit(status)
