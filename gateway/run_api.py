"""The gateway's local HTTP/WS listener: the native session WebSocket.

The listener serves exactly one route, the ticketed native session WebSocket at ``/api/ws``, which
every local CLI/TUI session attaches to. There is no dashboard application behind it: HTTP requests
answer 404 and any other WebSocket path is closed. The ticket and its profile binding are minted on
the owner-only control socket (a same-user peer), and only loopback peers may redeem one, so the
listener can bind before the agent loop starts and needs no browser auth layer.

The caller initializes session authority before starting this listener and owns all runtime services
and signals. This module owns only HTTP resources; it does not bootstrap an agent, scheduler, hosted
room, or a second gateway.
"""

import asyncio
from dataclasses import dataclass
import ipaddress
import logging
import os
import socket
import types
from typing import Any

logger = logging.getLogger(__name__)

# One listener per process: the session authority shares one process-local runtime.
_ACTIVE_RUNNER: Any = None
# A fixed port (a configured one) has to bind again while the last gateway's closed connections sit in
# TIME_WAIT. POSIX allows that with SO_REUSEADDR; on Windows that option lets another process bind
# the same port, and a rebind there does not wait on TIME_WAIT anyway.
_REUSE_FIXED_PORT = os.name != "nt"
# On Windows a fixed port is held for exclusive use instead: otherwise another process may bind it with
# SO_REUSEADDR, and a more specific address (127.0.0.1 under a 0.0.0.0 bind) then takes its connections.
_EXCLUSIVE_FIXED_PORT = os.name == "nt"


@dataclass
class GatewayAPIHandle:
    api_origin: str
    server: Any
    task: asyncio.Task
    app: Any
    socket: socket.socket


class SessionListenerFallback:
    """Answer everything the session listener does not serve: HTTP 404, other upgrades closed."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4404})
            return
        await send({"type": "http.response.start", "status": 404,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"error": "not_found"}'})


def _listener_socket(family, kind, proto, port: int, *, dual_stack: bool = False) -> socket.socket:
    """The listener's unbound socket; a fixed *port* may bind again at once (``_REUSE_FIXED_PORT``)
    or is held exclusively (``_EXCLUSIVE_FIXED_PORT``). A *dual_stack* IPv6 socket (the ``::``
    wildcard) takes IPv4 connections too."""
    listener = socket.socket(family, kind, proto)
    if dual_stack:
        # "::" means every address, as Linux binds it by default. Windows binds IPv6 only otherwise:
        # IPv4 clients would never reach the listener, and the exclusive hold below would cover the
        # IPv6 port alone, leaving 0.0.0.0 on the same port to another program.
        listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    if port and _REUSE_FIXED_PORT:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    elif port and _EXCLUSIVE_FIXED_PORT:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    return listener


def _api_origin(bind_host: str, port: int) -> str:
    """The ``api_origin`` native clients get for a listener bound to *bind_host*: a numeric loopback
    address, since clients accept only that (``localhost`` may resolve to either family)."""
    host = bind_host
    try:
        if not ipaddress.ip_address(bind_host).is_loopback:
            host = "::1" if bind_host == "::" else "127.0.0.1"
    except ValueError:
        host = "localhost"
    return f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"


def _require_loopback(host: str) -> None:
    """Native tickets are loopback-only grants; a non-loopback listener has no client that could
    authenticate, so refuse to start one instead of exposing an unauthenticated session socket."""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.strip().lower() == "localhost"
    if not loopback:
        raise RuntimeError("the gateway session listener binds loopback only")


async def start_gateway_api(runner, *, host: str = "127.0.0.1", port: int = 0) -> GatewayAPIHandle:
    global _ACTIVE_RUNNER
    from hermes_cli.web_server_boundary import SESSION_WS_MAX_BYTES
    from hermes_cli.web_server_lifecycle import build_listener_server

    if _ACTIVE_RUNNER is not None:
        raise RuntimeError("gateway API already started")
    _require_loopback(host)
    state = types.SimpleNamespace(bound_host=host, bound_port=None)
    fallback = SessionListenerFallback()
    config, server = build_listener_server(
        fallback, host, port, ws_max_size=SESSION_WS_MAX_BYTES, timeout_graceful_shutdown=5)
    family, kind, proto, _, address = socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM,
    )[0]
    listener = _listener_socket(family, kind, proto, port,
                                dual_stack=family == socket.AF_INET6 and address[0] == "::")
    _ACTIVE_RUNNER = runner
    try:
        listener.bind(address)
        if port:
            # Under SO_REUSEADDR another socket may bind a fixed port too, and the first to listen
            # owns it. Listening now settles that before the runtime API reports ready.
            listener.listen(config.backlog)
        listener.setblocking(False)
        state.bound_port = listener.getsockname()[1]
        # Loading the ASGI graph may fail too; it owns the same bound socket.
        if not config.loaded:
            config.load()
        config.loaded_app = GatewayRuntimeAPI(config.loaded_app, runner, state)
        # uvicorn's Server.startup()/main_loop() expect the lifespan object that _serve() would
        # otherwise create; the listener is built and started here, so bind it explicitly
        # (lifespan="off": there is no app lifespan to run).
        server.lifespan = config.lifespan_class(config)
        await server.startup(sockets=[listener])
        if not server.started or server.should_exit:
            raise RuntimeError("gateway API lifespan startup failed")
    except BaseException:
        listener.close()
        _ACTIVE_RUNNER = None
        raise

    async def serve():
        global _ACTIVE_RUNNER
        try:
            await server.main_loop()
        finally:
            try:
                await server.shutdown(sockets=[listener])
            finally:
                listener.close()
                _ACTIVE_RUNNER = None

    task = asyncio.create_task(serve(), name="gateway-api")
    return GatewayAPIHandle(
        # The address the socket bound, never a name: native clients accept only a numeric loopback
        # origin, and ``localhost`` may resolve to either family.
        api_origin=_api_origin(listener.getsockname()[0], state.bound_port),
        server=server, task=task, app=fallback, socket=listener,
    )


async def stop_gateway_api(handle: GatewayAPIHandle) -> None:
    """Drain sockets without stopping the session authority or taking signals."""
    handle.server.should_exit = True
    # The bootstrap supervisor reports listener failure. Cleanup must still
    # reach adapter/worker settlement when that listener raised or was cancelled.
    await asyncio.shield(asyncio.gather(handle.task, return_exceptions=True))


class GatewayRuntimeAPI:
    """Redeem private local tickets at the existing WS subprotocol boundary.

    Only the native session WebSocket is served. Local bootstrap never grants an exposure/worker
    ticket interactive permissions; readiness/drain gating runs before a ticket is redeemed.
    *state* carries the listener's ``bound_host`` (the native Host check and peer gate read it).
    """
    def __init__(self, app, runner, state):
        self.app, self.runner, self.state = app, runner, state

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'websocket' or scope.get('path') != '/api/ws':
            return await self._serve(scope, receive, send)
        started = accepted = False

        async def send_watched(message):
            nonlocal started, accepted
            started = True
            accepted = accepted or message.get('type') == 'websocket.accept'
            await send(message)

        try:
            return await self._serve(scope, receive, send_watched)
        except Exception as exc:
            # Uvicorn answers an upgrade that raised before accept with HTTP 500 and logs it only to
            # its own logger, never gateway.log: the dialing cron worker or managed worker sees a bare
            # InvalidStatus (#139922). Name the cause here; uvicorn still sends the 500, but only when
            # nothing was sent yet: a handler that had closed the upgrade already got its 403 out.
            if not accepted:
                logger.error('Gateway refused a session WebSocket upgrade from %s %s: %s: %s',
                             scope.get('hermes.gateway_socket_peer') or scope.get('client'),
                             'after its handler had refused it' if started else 'with HTTP 500',
                             type(exc).__name__, exc, exc_info=True)
            raise

    async def _serve(self, scope, receive, send):
        if scope['type'] not in {'http', 'websocket'} or scope.get('path') != '/api/ws':
            return await self.app(scope, receive, send)
        descriptor = getattr(self.runner, 'session_runtime_descriptor', None)
        if descriptor is None:
            return await self.app(scope, receive, send)
        draining_socket = (descriptor['state'] in {'ready', 'draining'}
            and (self.runner._draining or descriptor['state'] == 'draining')
            and scope['type'] == 'websocket' and scope['path'] == '/api/ws')
        if ((descriptor['state'] != 'ready' or self.runner._draining) and not draining_socket):
            if scope['type'] == 'websocket':
                await send({'type': 'websocket.close', 'code': 1013})
            else:
                await self.app(scope, receive, send)
            return
        # Capture before Uvicorn's proxy middleware rewrites scope.client (native grants, both kinds).
        scope['hermes.gateway_socket_peer'] = scope.get('client')
        original_receive = receive
        allow_draining = False
        admitted_in_wait = False
        from gateway.drain_control import restart_wait_open

        async def receive_admitted():
            message = await original_receive()
            # Only a socket admitted INTO the restart wait (to answer a parked prompt) outlives it. One
            # opened before the wait is cut as before: its client reconnects to the next owner, and a
            # held one (a kanban worker polling its card) would otherwise pin the drain to its cap.
            if ((descriptor['state'] != 'ready' or self.runner._draining) and not allow_draining
                    and not (admitted_in_wait and restart_wait_open(self.runner))):
                return {'type': 'websocket.disconnect', 'code': 1013}
            return message

        receive = receive_admitted
        from gateway.run_idle_exit import attached_client
        from starlette.websockets import WebSocket
        from hermes_cli.web_server_boundary import (
            _gateway_ws_ticket_from_subprotocol, ws_client_reason, ws_host_origin_reason,
        )
        state = self.state
        ws = WebSocket(scope, receive, send)
        ticket, reason = _gateway_ws_ticket_from_subprotocol(ws)
        # Native grants are loopback-only and never send an Origin; a browser upgrade (or any
        # credential-less dial) has no route left to authenticate on.
        native_peer = bool(ws.client) and ws.client.host in {'127.0.0.1', '::1'}
        if (reason != 'ok' or not native_peer or ws.headers.get('origin')
                or ws_host_origin_reason(ws, state) is not None or ws_client_reason(ws, state) is not None):
            await ws.close(code=4403)
            return
        operator = True
        try:
            grant = self.runner.session_ticket_store.redeem(ticket, profile_id=None, purpose='interactive')
        except PermissionError:
            operator = False
            try:
                grant = self.runner.session_ticket_store.redeem(ticket, profile_id=None, purpose='worker-adoption')
            except PermissionError:
                # Browser/OAuth tickets and legacy query credentials are gone with the dashboard.
                await ws.close(code=4403)
                return
        allow_draining = not operator
        # Decided here, at admission, not at the mint: a restart wait that opened after the client's
        # discovery still refuses the machine poller that asked to stay out of it (a Kanban worker),
        # which would otherwise hold the turn the wait is waiting on.
        admitted_in_wait = restart_wait_open(self.runner) and not grant.get('refuse_restart_wait')
        # A restart's after-turn wait still owns its turns: an interactive client attaches to answer
        # a parked approval/clarify (#139041); stop() closes this window.
        if ((descriptor['state'] != 'ready' or self.runner._draining) and not allow_draining
                and not admitted_in_wait):
            await ws.close(code=1013)
            return
        from gateway.session_authorities import authority_for_profile_id
        authority = authority_for_profile_id(self.runner, grant['profile_id'])
        if authority is None:
            await ws.close(code=4403)
            return
        # The ticket names the served profile; this connection binds to that home's authority.
        scope['hermes.session_authority'] = authority
        from gateway.session_contract import CANONICAL_GATEWAY_PROTOCOL
        from tui_gateway.ws import handle_ws
        from gateway.session_authorities import owner_scope
        with owner_scope(authority), attached_client(self.runner):
            await handle_ws(ws, auth_identity={'user_id': grant['subject'], 'provider': 'local',
                                              'profile_id': grant['profile_id'],
                                              'instance_id': grant['instance_id'],
                                              'capabilities': grant['capabilities'], 'native_bootstrap': True,
                                              'profile_scope': grant.get('scope', 'profile')},
                            subprotocol=CANONICAL_GATEWAY_PROTOCOL, operator=operator)
