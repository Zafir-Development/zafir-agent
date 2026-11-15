"""Transport liveness + build capability probes (``methods_voice.py`` hosts them)."""

from __future__ import annotations

from .base import Params, Result
from .registry import method


class PingParams(Params):
    pass


class PingResult(Result):
    pong: bool


method("ping", params=PingParams, result=PingResult,
       doc="Cheapest liveness probe; answered on the WS reader thread even while every agent is mid-turn.")


class GatewayCapabilitiesResult(Result):
    per_session_exclusive_submit: bool


method("gateway.capabilities", params=PingParams, result=GatewayCapabilitiesResult,
       doc="What THIS build enforces (a client withholds a feature unless advertised).")


class ClientCapabilitiesParams(Params):
    #: The client answers server→client requests (clarify, approval, sudo, …) — with a result or a -32601
    #: error for methods it has no handler for. A WebSocket client that never says so is treated as a
    #: build older than server→client requests and every such request fails fast for it.
    server_requests: bool = False


class ClientCapabilitiesResult(Result):
    #: Server→client request methods this backend may send.
    server_requests: list[str]
    #: This backend settles a server→client request as declined only once every attached client
    #: declined it (server_requests.py). An older backend settles on the first error, so a client
    #: sends the decline only when this is true.
    declines_not_shown: bool = False
    #: A canonical owner on this backend admits ``clarify_batch`` on ``prompt.submit``: the turn's
    #: multi-question clarify arrives as ONE ``clarify`` request answered with ``clarify.lock``, not
    #: one card per question. An older owner refuses the unknown key, so a client declares it only when
    #: this is true. (The legacy sidecar always asks the batch at once and is never sent the key.)
    canonical_clarify_batch: bool = False


method("client.capabilities", params=ClientCapabilitiesParams, result=ClientCapabilitiesResult,
       doc="What the calling client handles, sent once per connection (after gateway.ready); returns the "
           "server→client request methods this backend may send.")
