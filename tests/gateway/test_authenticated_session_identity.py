"""Native session subjects keep their durable creation and mutation retries."""
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_private_native_subject_preserves_existing_creation_and_mutation_retries(tmp_path, monkeypatch):
    from gateway import run
    from gateway.config import GatewayConfig
    from gateway.session import SessionStore
    from gateway.session_authority import initialize_session_authority
    from gateway.session_controls import AuthorityConnection
    from gateway.session_contract import SessionActor
    from gateway.session_local import create_local_session
    from gateway.session_mutations import mutate_session
    from hermes_state_runtime import RuntimeStoreError

    monkeypatch.setattr(run, '_load_gateway_config', lambda: {'platform_toolsets': {'cli': []}})
    store = SessionStore(tmp_path / 'sessions', GatewayConfig())
    runner = SimpleNamespace(session_store=store, _session_db=store._db, adapters={}, _draining=False)
    authority = await initialize_session_authority(runner, profile_id='fixture', instance_id='first')
    caps = frozenset({'session:create', 'session:read', 'session:control'})
    old = SessionActor('uid:1000', 'fixture', caps, 'old')
    params = {'request_id': 'original', 'source': 'cli', 'cwd': str(tmp_path), 'model': 'fixture', 'toolsets': []}
    ref = create_local_session(authority, old, params)
    native = AuthorityConnection(authority, object(), {'provider': 'local', 'user_id': old.subject,
        'profile_id': 'fixture', 'instance_id': 'first', 'capabilities': caps}).actor
    assert native.subject == old.subject
    assert create_local_session(authority, native, params) == ref
    edit = dict(session_id=ref.session_id, request_id='rename', expected_revision=0, operation='rename', payload={'title': 'Native preserved'})
    result = await mutate_session(authority, old, ref, edit)
    assert await mutate_session(authority, native, ref, edit) == result
    remote = AuthorityConnection(authority, object(), {'provider': 'local', 'user_id': old.subject}).actor
    with pytest.raises(RuntimeStoreError, match='permission_denied'):
        await authority.resolve(remote, ref)
