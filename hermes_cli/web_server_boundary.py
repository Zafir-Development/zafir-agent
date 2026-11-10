"""Listener boundary primitives for the native session WebSocket.

Host validation, the loopback peer gate and the native ticket subprotocol. Import-light on purpose
(no FastAPI): the gateway's session listener serves ``/api/ws`` without a web application and must
still reject a DNS-rebinding Host header and non-loopback peers before a ticket is redeemed.
"""

import re
import urllib.parse
from typing import Optional

# Accepted Host values for loopback binds. DNS rebinding TTL-flips an attacker
# hostname to 127.0.0.1 so the browser treats it as same-origin; validating Host
# at the app layer rejects it. See GHSA-ppp5-vxwm-4cf7.
_LOOPBACK_HOST_VALUES: frozenset = frozenset({"localhost", "127.0.0.1", "::1"})

# Starlette's TestClient reports the peer as "testclient"; treat it as
# loopback so tests don't need to rewrite request scope.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})

# A native client sends a whole base64 data URL in one JSON-RPC frame; uvicorn's 16 MiB default
# rejects files under the attach cap.
SESSION_WS_MAX_BYTES = 384 * 1024 * 1024


def _host_header_hostname(host_header: str) -> str:
    """Return a normalized hostname from a valid HTTP Host authority.

    Host headers are authorities, not full URLs. Reject ambiguous ports,
    malformed IPv6 brackets, and URL syntax so validation always fails closed.
    """
    value = (host_header or "").strip()
    if not value or "://" in value or any(c in value for c in '"\'<> \n\r\t/?#@'):
        return ""

    if value.startswith("["):
        close = value.find("]")
        if close == -1:
            return ""
        hostname = value[1:close]
        # Bracket notation is reserved for IPv6 literals.
        if ":" not in hostname:
            return ""
        suffix = value[close + 1:]
        if suffix and not re.fullmatch(r":\d+", suffix):
            return ""
        return hostname.lower()

    # Unbracketed IPv6 authorities are ambiguous with a port separator.
    if value.count(":") > 1:
        return ""
    if ":" in value:
        hostname, port = value.rsplit(":", 1)
        if not hostname or not port.isdigit():
            return ""
        return hostname.lower()
    return value.lower()


def _is_accepted_host(host_header: str, bound_host: str) -> bool:
    """True if the Host header targets the interface the listener bound to.

    Accepts the exact bound host (with or without port suffix) and loopback aliases when bound to
    loopback. The session listener binds loopback only, so a loopback alias is the whole set.
    """
    host_only = _host_header_hostname(host_header)
    if not host_only:
        return False
    bound_lc = bound_host.lower()
    if bound_lc in _LOOPBACK_HOST_VALUES:
        return host_only in _LOOPBACK_HOST_VALUES
    return host_only == bound_lc


_GATEWAY_WS_PROTOCOL = "hermes-gateway-v1"
_GATEWAY_WS_TICKET_PROTOCOL_PREFIX = "hermes-gateway-ticket."


def _gateway_ws_ticket_from_subprotocol(ws) -> tuple[str, str]:
    """Return ``(ticket, reason)`` from an unambiguous gateway protocol set."""
    raw = str(ws.headers.get("sec-websocket-protocol", "") or "")
    protocols = [value.strip() for value in raw.split(",") if value.strip()]
    ticket_protocols = [
        value for value in protocols if value.startswith(_GATEWAY_WS_TICKET_PROTOCOL_PREFIX)]
    if not ticket_protocols:
        return "", "none"
    if _GATEWAY_WS_PROTOCOL not in protocols or len(ticket_protocols) != 1:
        return "", "invalid"
    ticket = ticket_protocols[0][len(_GATEWAY_WS_TICKET_PROTOCOL_PREFIX):]
    return (ticket, "ok") if ticket else ("", "invalid")


def ws_client_reason(ws, state) -> Optional[str]:
    """Rejection reason token for the WebSocket peer, or None when allowed.

    Native tickets are loopback-only grants, so a non-loopback peer is refused here and an empty
    peer fails closed.
    """
    client_host = ws.client.host if ws.client else ""
    if not client_host:
        bound_host = (getattr(state, "bound_host", "") or "").strip().lower()
        return f"missing_or_empty_peer bound={bound_host or '?'}"
    if client_host in _LOOPBACK_HOSTS:
        return None
    return f"peer_not_loopback peer={client_host}"


def ws_host_origin_reason(ws, state) -> Optional[str]:
    """``host_mismatch …`` / ``origin_mismatch …`` under listener *state*, or None when allowed.

    HTTP middleware does not run for WebSocket routes, so the DNS-rebinding Host check is repeated
    here. A native client sends no Origin; any Origin header is a browser upgrade, which has no
    credential left to authenticate with.
    """
    bound_host = getattr(state, "bound_host", None)
    if not bound_host:
        return None
    host_header = ws.headers.get("host", "")
    if not _is_accepted_host(host_header, bound_host):
        return f"host_mismatch host={host_header or '?'} bound={bound_host}"
    origin = ws.headers.get("origin", "")
    if not origin:
        return None
    try:
        parsed = urllib.parse.urlparse(origin)
    except ValueError:  # malformed authority, e.g. "http://[::1" — fail closed
        parsed = None
    if parsed is not None and parsed.scheme not in {"http", "https"}:
        return None
    return f"origin_mismatch origin={origin} bound={bound_host}"
