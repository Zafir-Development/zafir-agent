"""Idle-work snapshot shared by backend retirement (async delegation) and the updater.

Reads the in-process session table, delegation, cron and human-input ledgers. Unreadable state is
indeterminate, never idle. This snapshot alone is NOT permission to retire: only
``backend_retirement.RetirementFence.prepare`` freezes admission before taking the snapshot, and
only a confirmed commit permits the caller to stop that exact backend generation.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

_log = logging.getLogger(__name__)

_probe_failure_logged = False


def _session_work_in_flight(session: dict) -> bool:
    if any(session.get(key) for key in ("running", "queued_prompt", "queued_prompts", "_auto_continue_scheduled")):
        return True
    return any(thread.is_alive() for key in ("_run_thread", "_agent_build_thread")
               if (thread := session.get(key)) is not None)


def busy_ledger() -> Optional[str]:
    """Name the ledger that holds work — ``"retirement_admission"``, ``"session:<id>"``,
    ``"delegation"``, ``"cron:<job ids>"`` — ``""`` when every ledger is empty, ``None`` when one
    cannot be read, so a caller that refuses to retire says WHICH work it is protecting.

    Session work lives on ``tui_gateway.server`` (the voice mixin's helper is bound into that
    namespace). Cron runs live outside that table (``cron.scheduler.get_running_job_ids``, the same
    ledger the gateway shutdown drain reads): without it a daily job mid-run reported "no turn" and
    the exit killed it (#107485). None keeps the backend alive forever, so the cause is logged once —
    a silent never-exits would be the original bug with a new face."""
    global _probe_failure_logged
    try:
        import tui_gateway.server as gateway
        from hermes_cli.backend_retirement import retirement

        if retirement.active_count():
            return "retirement_admission"
        with gateway._sessions_lock:
            busy_sessions = [sid for sid, s in gateway._sessions.items() if _session_work_in_flight(s)]
        if busy_sessions:
            return "session:" + ",".join(str(sid) for sid in busy_sessions)
        from tools.async_delegation import active_count
        from cron.scheduler import get_running_job_ids
        if active_count():
            return "delegation"
        running_jobs = get_running_job_ids()
        return "cron:" + ",".join(sorted(running_jobs)) if running_jobs else ""
    except Exception:
        if not _probe_failure_logged:
            _probe_failure_logged = True
            _log.warning("idle turn probe unavailable; this backend will not self-retire", exc_info=True)
        return None


def pending_human_input() -> Optional[int]:
    """Count of prompts waiting on a human (clarify/approval/sudo/secret requests plus queued
    gateway approvals); ``None`` when a ledger cannot be read."""
    global _probe_failure_logged
    try:
        from tui_gateway import server_requests
        from tools.approval import pending_gateway_approval_count

        return server_requests.open_request_count() + pending_gateway_approval_count()
    except Exception:
        if not _probe_failure_logged:
            _probe_failure_logged = True
            _log.warning("idle input probe unavailable; this backend will report indeterminate",
                         exc_info=True)
        return None


def idle_proof(turn_probe: Callable[[], bool | str | None] = busy_ledger,
               input_probe: Callable[[], Optional[int]] = pending_human_input) -> dict:
    """``{"idle": True | False | None, "reason": str | None}`` plus ``"detail"`` naming the busy ledger.

    ``True`` only when no turn is in flight (session table AND cron ledger) and nothing is waiting
    on a human. ``None`` whenever either probe is indeterminate — the caller treats it exactly like
    busy. ``turn_probe`` may answer with a bool or with :func:`busy_ledger`'s name; the name is
    surfaced as ``detail`` so a backend that refuses to retire says which work it is protecting.
    """
    turn = turn_probe()
    if turn is None:
        return {"idle": None, "reason": "turn_probe_unavailable"}
    if turn:
        return {"idle": False, "reason": "turn_in_flight", "detail": turn if isinstance(turn, str) else None}
    pending = input_probe()
    if pending is None:
        return {"idle": None, "reason": "input_probe_unavailable"}
    if pending:
        return {"idle": False, "reason": "awaiting_human_input"}
    return {"idle": True, "reason": None}
