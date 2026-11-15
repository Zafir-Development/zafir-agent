"""Restart supervised gateway profiles from a clean Python generation.

The normal update command keeps executing in the interpreter that started before
``git pull``.  This module is deliberately small: it imports no gateway code
itself and launches the regular per-profile gateway command in a new
interpreter.  It is used only after the in-process restart phase has raised, so
that the recovery path cannot inherit the stale ``sys.modules`` graph that
caused the failure.

Outcome vocabulary (deliberately conservative):

- ``verified``          — the relaunch command exited 0 AND the profile's
  systemd unit was independently observed ``active`` afterwards.  This is the
  only outcome that may claim supervisor coverage.
- ``relaunch_attempted`` — the relaunch command exited 0 but no independent
  supervisor observation was possible (non-systemd supervisor, ``systemctl``
  missing, or the unit probe was inconclusive).  ``rc == 0`` from
  ``gateway restart`` is not proof that the new code generation is running,
  so this outcome must never be treated as verified coverage.
- ``failed``            — the relaunch command errored, timed out, or exited
  non-zero.

An abort can strand gateway profiles in the pre-update Python generation
(#92145):

- **gateway profiles**, relaunched through the existing per-profile
  ``hermes_cli.main -p <profile> gateway restart`` command; and
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from typing import Any

_RECOVERY_ENV = "HERMES_UPDATE_RESTART_RECOVERY"
_GATEWAY_MARKERS = ("_HERMES_GATEWAY", "HERMES_GATEWAY", "HERMES_GATEWAY_MODE")
_PROFILE_RESTART_TIMEOUT = 90
_VERIFY_TIMEOUT = 15
from hermes_constants import PROFILE_ID_RE as _PROFILE_ID_RE

_SUPERVISOR_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def _run_quiet(run: Callable[..., Any], argv: list[str], *, timeout: int, **extra: Any) -> Any | None:
    """Run ``argv`` capturing text output; ``None`` when it errors or times out."""
    try:
        return run(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False, timeout=timeout, **extra,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _stdout(result: Any) -> str:
    return (getattr(result, "stdout", "") or "").strip()


def _succeeded(result: Any) -> bool:
    return result is not None and getattr(result, "returncode", 1) == 0


def _launch_profile() -> str:
    """Profile this recovery process was launched as: ``<root>/profiles/<name>`` in ``HERMES_HOME`` names it,
    anything else is the default profile. Mirrors ``hermes_cli.profiles.profile_root_for_env_home`` without
    importing it — this module stays stdlib-only at import time."""
    home = os.environ.get("HERMES_HOME", "").strip()
    if home:
        path = os.path.normpath(home)
        if os.path.basename(os.path.dirname(path)) == "profiles":
            return os.path.basename(path)
    return "default"


def _child_environment(profile: str | None = None) -> dict[str, str]:
    """Return an environment that cannot self-identify as the gateway owner.

    One updater environment relaunches EVERY profile, so a child for another profile would inherit
    this process's authorization gates (``DISCORD_ALLOWED_CHANNELS``, ``GATEWAY_ALLOW_ALL_USERS`` ...)
    and enforce them as its own — its ``.env`` only overwrites the keys it defines (#113270). Gates are
    dropped when *profile* is not the launch profile; a same-profile child keeps an operator export.

    Restarting the host multiplexer from a named profile does not copy this process's environ: the
    child is ``host_gateway_child_env`` (``served_profile_child_env`` for the default root) so the
    launching profile's platform credentials never become the primary adapter's.
    """
    launch = _launch_profile()
    target = profile if profile is not None else launch
    if target == "default" and launch != "default":
        from tools.environments.local import host_gateway_child_env
        env = host_gateway_child_env()
    else:
        env = os.environ.copy()
        if profile is not None and profile != launch:
            from tools.environments.local_env_policy import strip_profile_gate_env
            strip_profile_gate_env(env)
    for marker in _GATEWAY_MARKERS:
        env.pop(marker, None)
    env[_RECOVERY_ENV] = "1"
    return env


def _run_profile_restart(profile: str, *, run: Callable[..., Any]) -> bool:
    """Run one profile restart without inheriting the updater's process state."""
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "env": _child_environment(profile)}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        # detached-spawn: ok — awaited with a timeout; the gateway restart it runs must not share the updater's group
        kwargs["start_new_session"] = True
    # `--interrupt`: the update owns this restart (drain-first, 31637312899); a live session must not
    # strand the profile on pre-update code the way a refusal would. `--detach`: this bounded call
    # must not itself become a service-less profile's gateway (killed at the timeout below).
    argv = [sys.executable, "-m", "hermes_cli.main", "-p", profile, "gateway", "restart", "--interrupt", "--detach"]
    return _succeeded(_run_quiet(run, argv, timeout=_PROFILE_RESTART_TIMEOUT, **kwargs))


def _systemd_unit_candidates(profile: str) -> tuple[str, ...]:
    """Unit names the existing systemd gateway lifecycle produces per profile."""
    if profile == "default":
        return ("hermes-gateway.service", "gateway.service", "gateway-default.service")
    return (f"hermes-gateway-{profile}.service", f"gateway-{profile}.service")


def _systemd_verified_active(profile: str, *, run: Callable[..., Any]) -> bool:
    """True only when systemd itself reports the profile's unit active — the observation separating
    ``verified`` from ``relaunch_attempted``. Any failure (no ``systemctl``, probe error, unit not
    ``active``) means we could NOT verify, never that the restart failed."""
    systemctl = shutil.which("systemctl")
    return bool(systemctl) and any(
        _unit_is_active([systemctl, "--user"], unit, run=run, require_rc0=True)
        for unit in _systemd_unit_candidates(profile)
    )


def _host_state_dir() -> str:
    """The path ``gateway.host_rendezvous.host_state_dir()`` resolves, computed locally.

    This module imports no Hermes code at runtime — importing the freshly pulled tree is exactly
    what aborted the phase that calls us — so the rule is duplicated here rather than shared.
    """
    override = os.environ.get("HERMES_GATEWAY_LOCK_DIR")
    if override:
        return override
    state_home = os.environ.get("XDG_STATE_HOME") or ""
    if not os.path.isabs(state_home):
        state_home = os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(state_home, "hermes", "gateway-locks")


def _pid_is_live(pid: int) -> bool:
    """Liveness of ``pid``: ``psutil`` when importable, else the POSIX signal-0 probe.

    The signal probe is POSIX-only by construction — on Windows ``os.kill(pid, 0)`` sends a real
    control event and can kill the target — so an unimportable psutil there means "cannot prove".
    """
    try:
        import psutil

        return bool(psutil.pid_exists(pid))
    except Exception:
        pass
    if os.name == "nt":
        return False
    try:
        os.kill(pid, 0)  # windows-footgun: ok — POSIX-only branch, guarded by os.name above
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _host_served_profiles() -> set[str]:
    """Profiles the ONE live host gateway multiplexes, from its rendezvous record.

    Restarting any one of them restarts the same process, so they are a single restart target.
    Empty (no collapsing, today's per-profile behaviour) when the record is absent, unreadable,
    dead, or when liveness cannot be probed — a missed collapse costs an extra restart, a wrong
    one would skip a profile that really has its own process.
    """
    try:
        with open(os.path.join(_host_state_dir(), "host-gateway.json"), encoding="utf-8-sig") as handle:
            record = json.load(handle)
    except (OSError, UnicodeDecodeError, ValueError):
        return set()
    if not isinstance(record, dict) or record.get("role") != "gateway":
        return set()
    pid = record.get("pid")
    profiles = record.get("profiles")
    if not isinstance(pid, int) or pid <= 0 or not isinstance(profiles, list) or not _pid_is_live(pid):
        return set()
    return {name for name in profiles if isinstance(name, str) and name}


def restart_profiles(
    profiles: Iterable[str], *, supervisors: Mapping[str, str] | None = None, run: Callable[..., Any] = subprocess.run
) -> dict[str, Any]:
    """Restart the supplied profiles (only ones whose inventory identified a service supervisor).

    Profiles served by the SAME host gateway process are one restart target: a host multiplexes
    every profile, so N payload profiles meant N sequential ``gateway restart`` calls, each
    killing the successor the previous pass had just verified. The group is restarted exactly
    once through one representative and the rest are reported under ``covered`` with that
    restart's outcome.

    A profile only lands in ``verified`` when its supervisor is systemd and ``systemctl --user is-
    active`` independently confirms the unit after the relaunch command succeeded.
    """
    supervisors = supervisors or {}
    result: dict[str, Any] = {"verified": [], "relaunch_attempted": [], "failed": []}
    requested = sorted({p for p in profiles if isinstance(p, str) and p})
    served = _host_served_profiles()
    group = [profile for profile in requested if profile in served]
    representative = group[0] if len(group) > 1 else None
    covered = group[1:] if representative else []
    for profile in requested:
        if profile in covered:
            continue
        if not _run_profile_restart(profile, run=run):
            bucket = "failed"
        elif supervisors.get(profile) == "systemd" and _systemd_verified_active(profile, run=run):
            bucket = "verified"
        else:
            bucket = "relaunch_attempted"
        result[bucket].append(profile)
        if profile == representative:
            # One process: the representative's observed outcome IS these profiles' outcome.
            result[bucket].extend(covered)
    result["covered"] = {representative: covered} if representative else {}
    return result


def _unit_is_active(scope: list[str], unit: str, *, run: Callable[..., Any], require_rc0: bool = False) -> bool:
    result = _run_quiet(run, scope + ["is-active", unit], timeout=_VERIFY_TIMEOUT)
    if result is None or (require_rc0 and not _succeeded(result)):
        return False
    return _stdout(result) == "active"


def _parse_payload(stream) -> tuple[list[str], dict[str, str]]:
    payload = json.load(stream)
    if not isinstance(payload, dict):
        payload = {}
    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        raise ValueError("recovery payload must contain a profiles list")
    if any(not isinstance(profile, str) or not _PROFILE_ID_RE.fullmatch(profile) for profile in profiles):
        raise ValueError("recovery profiles contain an invalid profile id")
    raw_supervisors = payload.get("supervisors")
    supervisors: dict[str, str] = {}
    if raw_supervisors is not None:
        if not isinstance(raw_supervisors, dict) or any(
            not isinstance(profile, str)
            or not isinstance(supervisor, str)
            or not _PROFILE_ID_RE.fullmatch(profile)
            or not _SUPERVISOR_RE.fullmatch(supervisor)
            for profile, supervisor in raw_supervisors.items()
        ):
            raise ValueError("recovery supervisors map is invalid")
        supervisors = dict(raw_supervisors)
    return profiles, supervisors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdin", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.stdin:
        parser.error("this command is an internal update-recovery entry point")

    try:
        profiles, supervisors = _parse_payload(sys.stdin)
        result = restart_profiles(profiles, supervisors=supervisors)
    except (ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "error": str(exc), "verified": [], "relaunch_attempted": [], "failed": [], "covered": {},
        }))
        return 2

    print(json.dumps(result, sort_keys=True))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
