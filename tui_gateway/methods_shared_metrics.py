"""Shared-metrics consent JSON-RPC handlers (the RPC twin of ``hermes setup``'s Shared Metrics
section). Both opt-ins live in the focused profile's config.yaml exactly where the wizard writes
them — ``telemetry.shared_metrics.enabled`` (local collection) and ``.send`` (daily upload) — so the
CLI and a client can never disagree about the answer. ``shared_metrics.set`` enforces the wizard's
invariant (sending needs collection) and reconciles the consent windows in the local store on every
change, through the same single writer the wizard uses.
Bodies are rebound onto server.py's globals (method_ctx.bind_module) and reference them bare.
"""

import logging

from .method_ctx import HandlerRegistry, bind_module

logger = logging.getLogger(__name__)
_registry = HandlerRegistry()
method = _registry.method
_profile_scoped = _registry.profile_scoped


def _shared_metrics_consent(cfg) -> dict:
    """The one ``{enabled, send, decided, reask}`` reading every surface shares (CLI offer included)."""
    from hermes_cli.observability.shared_metrics_consent import consent_state

    return consent_state(cfg)


def _tui_model_friction(signal, session, turns=1):
    from hermes_cli.observability.shared_metrics_model import record_model_friction
    record_model_friction(
        signal, session_id=session.get("session_key"), agent=session.get("agent"),
        hermes_home=session.get("profile_home"), turns=turns)


@method("shared_metrics.status")
@_profile_scoped
def _(rid, params: dict) -> dict:
    """``{enabled, send, decided, reask}`` for the focused profile. A pure read of config.yaml (no defaults
    merged, so ``decided`` sees only what the user wrote)."""
    try:
        return _ok(rid, _shared_metrics_consent(_load_cfg()))
    except Exception as e:
        return _err(rid, 5095, str(e))


@method("shared_metrics.set")
@_profile_scoped
def _(rid, params: dict) -> dict:
    """Write both opt-ins at once and reconcile the consent windows. ``send`` is forced off when
    ``enabled`` is off (the wizard's rule: sending cannot outlive collection, and turning collection
    off withdraws send consent). Answers the stored ``{enabled, send, decided, reask}``."""
    enabled = params.get("enabled") is True
    send = enabled and params.get("send") is True
    from hermes_cli.config_backend import ConfigWriteError, supports_file_tooling
    from hermes_cli.observability.shared_metrics_consent import OFFER_VERSION, set_answer
    try:
        if supports_file_tooling():
            cfg = _load_cfg_raw()
            set_answer(cfg, enabled, send)
            _save_cfg(cfg)
        else:
            # Explicit keys: refused as a whole when locked, never saved-minus-the-locked-part
            # while the consent bookkeeping below records the proposed answer.
            _write_config_changes({"telemetry.shared_metrics.enabled": enabled,
                                   "telemetry.shared_metrics.send": send,
                                   "telemetry.shared_metrics.offer_version": OFFER_VERSION})
            cfg = _load_cfg_raw()
    except ConfigWriteError as e:
        return _err(rid, 4002, str(e))
    except Exception as e:
        return _err(rid, 5096, str(e))
    from hermes_cli.setup import _record_send_consent_change
    # Unconditional, like the wizard: a send key already false may still have an open window.
    _record_send_consent_change(enabled=send)
    if not enabled:
        from hermes_cli.observability.shared_metrics_process import purge_pending_receipts
        from hermes_constants import get_hermes_home

        purge_pending_receipts(get_hermes_home())
    return _ok(rid, _shared_metrics_consent(cfg))


@method("shared_metrics.slash_command")
@_profile_scoped
def _(rid, params: dict) -> dict:
    """The Ink TUI dispatcher calls this once per user-typed slash command, locally
    handled ones included; the gateway never counts slash.exec / command.dispatch itself, so
    each command lands exactly once. Always ``{ok: true}`` (the events API never raises)."""
    from hermes_cli.observability.shared_metrics_events import record_slash_command

    record_slash_command(command=str(params.get("command") or ""), surface=_resolve_session_platform())
    return _ok(rid, {"ok": True})


@method("shared_metrics.startup_latency")
@_profile_scoped
def _(rid, params: dict) -> dict:
    """The Ink TUI (gateway ready) reports its own launch -> ready time once per launch;
    ``launch_id`` latches it here too, so a reconnect to this backend never re-counts. The client's
    declared surface wins over env detection. Always ``{ok: true}``."""
    from hermes_cli.observability.shared_metrics_startup import record_rpc_startup_latency

    record_rpc_startup_latency(
        client_surface=params.get("surface") or _resolve_session_platform(), elapsed_ms=params.get("elapsed_ms"),
        launch_id=params.get("launch_id"),
    )
    return _ok(rid, {"ok": True})


def register(server) -> None:
    bind_module(globals(), server, skip=("_",))
