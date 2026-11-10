"""Native session-ticket helpers for loopback gateway fixture peers.

A fixture runner is a bare ``GatewayRunner``: unlike production bootstrap it publishes neither the
runtime descriptor nor the ticket store, so the session listener has nothing to admit against.
``prepare_listener`` publishes both for the fixture's one launch authority, and ``subprotocols``
puts a fresh one-shot ticket in an upgrade's WebSocket subprotocol set (the only credential the
native ``/api/ws`` accepts).
"""
from __future__ import annotations

GATEWAY_WS_PROTOCOL = 'hermes-gateway-v1'
GATEWAY_WS_TICKET_PREFIX = 'hermes-gateway-ticket.'


def _authority(runner):
    authority = getattr(runner, 'session_authority', None)
    if authority is None:
        raise RuntimeError('fixture has no session authority to bind native tickets to')
    return authority


def launch_home(runner) -> str:
    """The served profile this listener's tickets are bound to: the launch authority's own home."""
    return str(_authority(runner).profile_id)


def prepare_listener(runner, *, state: str = 'ready'):
    """Publish the runtime descriptor and one-profile ticket store the session listener redeems against.

    The ticket store shares the authority's ``instance_id`` and serves only its home: the connection's
    identity must match both, or every RPC answers ``permission_denied``.
    """
    from gateway.runtime_bootstrap import TicketStore
    authority = _authority(runner)
    instance_id = authority.instance_id
    home = str(authority.profile_id)
    runner.session_runtime_descriptor = {
        'instance_id': instance_id, 'runtime_protocol': 1, 'state': state,
        'capabilities': [], 'served_profiles': [{'profile_id': home, 'home': home}],
    }
    runner.session_ticket_store = TicketStore(instance_id, frozenset({home}))
    return runner.session_ticket_store


def ws_url(api) -> str:
    """The session listener's loopback ``/api/ws`` URL."""
    return api.api_origin.replace('http:', 'ws:') + '/api/ws'


def subprotocols(runner, *, subject: str, purpose: str = 'interactive',
                 scope: str = 'profile') -> list[str]:
    """A fresh one-shot native ticket beside the canonical gateway protocol."""
    store = getattr(runner, 'session_ticket_store', None)
    if store is None:
        raise RuntimeError('prepare_listener() must run before minting native tickets')
    ticket = store.mint(profile_id=launch_home(runner), subject=subject,
                        purpose=purpose, scope=scope)
    return [GATEWAY_WS_PROTOCOL, GATEWAY_WS_TICKET_PREFIX + ticket]
