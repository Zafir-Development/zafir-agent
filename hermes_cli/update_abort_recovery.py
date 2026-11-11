"""Fresh-process gateway recovery after the update's in-process restart phase aborts."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)


def _surviving_pre_update_serve_runtimes(plan) -> list[dict]:
    """Pre-update serve/dashboard runtimes that are STILL the same process — i.e. live on the
    pre-update code generation. Identity is the incarnation ``(pid, create_time)``, never the PID
    alone: ``ledger_entries()`` prunes dead entries, but a correctly restarted serve can come back
    on the same number. Fail closed on missing evidence (unreadable ledger, no incarnation on either
    side): the runtime counts as surviving."""
    planned: dict[int, dict] = {}
    try:
        for runtime in getattr(plan, "runtimes", ()) or ():
            if getattr(runtime, "kind", None) not in ("serve", "dashboard"):
                continue
            pid = getattr(runtime, "pid", None)
            if not isinstance(pid, int) or pid <= 0:
                continue
            detail = getattr(runtime, "detail", None)
            detail = detail if isinstance(detail, dict) else {}
            planned[pid] = {
                "pid": pid, "kind": str(getattr(runtime, "kind", "")),
                "profile": str(getattr(runtime, "profile", "")),
                "supervisor": str(getattr(runtime, "supervisor", "")),
                "_create_time": _numeric(detail.get("create_time"))}
            if detail.get("systemd_unit"):
                # The owning unit and scope name the exact restart command (#141021).
                planned[pid]["systemd_unit"] = str(detail["systemd_unit"])
                planned[pid]["systemd_scope"] = detail.get("systemd_scope")
    except Exception as exc:
        logger.debug("Could not read planned serve runtimes: %s", exc)
        return []
    if not planned:
        return []
    try:
        from hermes_cli.process_identity import ledger_entries
        live: dict[int, float | None] = {
            entry["pid"]: _numeric(entry.get("create_time"))
            for entry in ledger_entries()
            if entry.get("purpose") in ("serve", "dashboard") and isinstance(entry.get("pid"), int)}
    except Exception as exc:
        logger.debug("Serve/dashboard survivor probe failed: %s", exc)
        live = None
    def _still_live(pid, row) -> bool:
        if live is None:
            return True
        if pid not in live:
            return False
        planned_created, live_created = row["_create_time"], live[pid]
        # Same number, different process: the pre-update runtime is gone and something new
        # registered under its PID. Not a survivor.
        return not (
            planned_created is not None and live_created is not None
            and abs(float(live_created) - float(planned_created)) >= 2.0)

    # The operator-facing row drops the incarnation (a matching key only).
    survivors = [
        {k: v for k, v in row.items() if k != "_create_time"}
        for pid, row in planned.items() if _still_live(pid, row)]
    return sorted(survivors, key=lambda row: row["pid"])


def _numeric(value):
    return value if isinstance(value, (int, float)) else None


def _run_fresh_recovery_process(
    profiles, candidates, *, gateway_mode: bool
) -> subprocess.CompletedProcess | None:
    """Spawn ``hermes_cli.update_restart_recovery --stdin`` detached from this process; None when it
    could not run (no systemd-run in gateway mode, OSError, timeout) — the caller fails closed."""
    command = [sys.executable, "-m", "hermes_cli.update_restart_recovery", "--stdin"]
    env = os.environ.copy()
    env["HERMES_UPDATE_RESTART_RECOVERY"] = "1"
    for marker in ("_HERMES_GATEWAY", "HERMES_GATEWAY", "HERMES_GATEWAY_MODE"):
        env.pop(marker, None)

    # A gateway-triggered update may run inside the gateway's systemd cgroup: put the recovery in a
    # transient user scope or KillMode terminates it with the old service. No systemd-run -> fail
    # closed rather than pretend the in-cgroup child is independent.
    if gateway_mode and sys.platform == "linux":
        systemd_run = shutil.which("systemd-run")
        if not systemd_run:
            logger.warning("Cannot isolate fresh gateway recovery from the gateway cgroup")
            return None
        command = [systemd_run, "--user", "--scope", "--quiet", "--collect", "--", *command]

    kwargs = {
        "input": json.dumps({"profiles": profiles, "supervisors": candidates}),
        "capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace",
        "env": env,
        "timeout": max(180, 30 + 90 * len(profiles))}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0))
    else:
        # detached-spawn: ok — awaited with a timeout; the gateway restart it runs must not share the updater's group
        kwargs["start_new_session"] = True
    try:
        return subprocess.run(command, **kwargs, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Fresh gateway restart recovery failed: %s", exc)
        return None


def _recover_gateway_restart_after_abort(
    plan, *, gateway_mode: bool, skip_profiles: set[str] | None = None
) -> dict[str, list]:
    """Retry supervised gateway restarts from a clean Python process. Only inventory-classified
    supervisor-owned profiles.

    """
    from hermes_cli.update_cmd import _gateway_recovery_partition
    candidates, skipped = _gateway_recovery_partition(plan, skip_profiles=skip_profiles)
    profiles = sorted(candidates)
    def _result(requested, verified, relaunch_attempted, failed) -> dict[str, list]:
        return {
            "requested": requested, "verified": verified, "relaunch_attempted": relaunch_attempted,
            "failed": failed, "skipped": skipped}

    if not profiles:
        return _result([], [], [], [])

    def _all_failed() -> dict[str, list]:
        return _result(profiles, [], [], profiles)

    result = _run_fresh_recovery_process(profiles, candidates, gateway_mode=gateway_mode)
    if result is None:
        return _all_failed()
    if result.returncode != 0:
        logger.warning("Fresh gateway restart recovery exited %s", result.returncode)
        return _all_failed()
    try:
        recovery_result = json.loads(result.stdout or "")
        verified = recovery_result.get("verified")
        relaunch_attempted = recovery_result.get("relaunch_attempted")
        failed = recovery_result.get("failed")
    except (AttributeError, TypeError, ValueError):
        logger.warning("Fresh gateway restart recovery returned invalid JSON")
        return _all_failed()

    buckets = (verified, relaunch_attempted, failed)
    reported: list[str] = []
    if all(isinstance(bucket, list) for bucket in buckets):
        reported = [*verified, *relaunch_attempted, *failed]
    if (
        not all(isinstance(bucket, list) for bucket in buckets)
        or any(not isinstance(profile, str) for profile in reported)
        or set(reported) != set(profiles) or len(reported) != len(set(reported))):
        logger.warning("Fresh gateway restart recovery returned incomplete profiles")
        return _all_failed()

    verified, relaunch_attempted, failed = sorted(verified), sorted(relaunch_attempted), sorted(failed)
    covered_map = recovery_result.get("covered")
    for owner, others in (covered_map if isinstance(covered_map, dict) else {}).items():
        if isinstance(owner, str) and isinstance(others, list) and others:
            print(
                f"  • One host gateway serves {owner} and {', '.join(str(o) for o in others)} — "
                f"restarted once through {owner}; that restart is their outcome."
            )
    for names, text in (
        (verified, "  ✓ Restarted supervised gateway(s) in a fresh process (systemd-verified active): "),
        (relaunch_attempted, "  ⚠ Relaunch attempted in a fresh process but not"
                             " supervisor-verified (check these gateways manually): ")):
        if names:
            print(text + ", ".join(names))
    return _result(profiles, verified, relaunch_attempted, failed)


def _warn_stale_serve_runtimes(rows) -> None:
    """Name the serve/dashboard processes still on pre-update code: ``hermes serve`` hosts
    ``tui_gateway.server``, and an un-restarted unit keeps the pre-pull ``sys.modules`` graph so
    every chat turn fails with an ``ImportError`` no gateway row explains."""
    if not rows:
        return
    print(
        "  ⚠ These serve/dashboard processes still run pre-update code"
        " (they started before the checkout changed):")
    for row in rows:
        print(
            f"      pid {row.get('pid')} — {row.get('kind')}"
            f" (profile {row.get('profile') or 'default'}, {row.get('supervisor') or 'unknown'})")
    unit_rows = [row for row in rows if row.get("supervisor") == "systemd"]
    if len(unit_rows) < len(rows):
        print("    Ask their owner to relaunch `hermes serve` / `hermes dashboard`, or reconnect Desktop for an SSH backend.")
    # A unit-managed backend restarts through its own unit and scope — never "ask the owner to
    # relaunch", and never a hardcoded user-scope hermes-serve (#141021).
    from hermes_cli.main_dashboard import _format_restart_commands, _systemd_restart_commands

    for row in unit_rows:
        commands = _systemd_restart_commands(row.get("systemd_unit") or "<unit>", row.get("systemd_scope"))
        print(f"    pid {row.get('pid')} is managed by systemd: {_format_restart_commands(commands)}")
    if sys.platform == "darwin" and any(row.get("supervisor") == "launchd" for row in rows):
        print("    For launchd-managed backends: `launchctl kickstart -k gui/$UID/<label>`.")


def _abort_recovery_is_complete(
    *, planned_gateway_profiles, covered_gateway_profiles, recovery_result
) -> bool:
    """May a fresh-process recovery clear the incomplete flag? Only when every planned gateway
    has a verified outcome. An empty gateway set is deliberately not completeness:
    ``_restart_phase_failure_is_incomplete`` decides.
    """
    result = recovery_result or {}
    return bool(
        planned_gateway_profiles
        and set(planned_gateway_profiles) <= set(covered_gateway_profiles)
        and not (result.get("failed") or result.get("relaunch_attempted")))
