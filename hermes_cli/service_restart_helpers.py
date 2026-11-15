"""Supervisor discovery and restart-command helpers for legacy Hermes service backends.

The ``hermes dashboard`` / ``hermes serve`` commands are gone; the update pipeline still stops and
restarts backends an older release left running. This module answers "which systemd unit / launchd
job owns this PID" (positively, from the unit's live ``MainPID`` or the loaded job) and renders the
restart command a user should run. Read-only: nothing here restarts or stops a process.
"""

import os
import re
import subprocess
import sys
from pathlib import Path


_SYSTEMCTL_ERRORS = (FileNotFoundError, subprocess.TimeoutExpired, OSError)


def _run_probe(cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess:
    """Captured, text-decoded ``subprocess.run`` for short local probes (systemctl, ps)."""
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def _parse_backend_runtime(command: str) -> tuple[str, str, int] | None:
    """Best-effort parse of a legacy backend cmdline into mode, host, and port.

    The mode is the canonical holder subcommand, never an argv substring: this gates the launchd
    backend inventory (a kill + kickstart path) and ``--status`` (#121156).
    """
    from hermes_cli.update_cmd_windows import _hermes_holder_subcommand
    mode = _hermes_holder_subcommand(command)
    if mode not in ("dashboard", "serve"):
        return None

    port = 9119
    host = "127.0.0.1"

    port_match = re.search(r"(?:^|\s)--port(?:=|\s+)(\d+)", command)
    if port_match:
        try:
            port = int(port_match.group(1))
        except ValueError:
            return None

    host_match = re.search(r"(?:^|\s)--host(?:=|\s+)(\"[^\"]+\"|'[^']+'|\S+)", command)
    if host_match:
        host = host_match.group(1).strip("\"'") or "127.0.0.1"

    return mode, host, port


def _pid_unified_cgroup_entries(pid: int):
    """Yield the ``0::<path>`` cgroup paths from ``/proc/<pid>/cgroup``; nothing when unreadable."""
    try:
        cgroup_path = Path(f"/proc/{pid}/cgroup")
        if not cgroup_path.is_file():
            return
        text = cgroup_path.read_text(encoding="utf-8-sig", errors="replace")
    except (OSError, PermissionError):
        return
    for line in text.splitlines():
        parts = line.strip().split("::", 1)
        if len(parts) == 2:
            yield parts[1]


def _get_systemd_service_for_pid(pid: int) -> str | None:
    """The systemd service unit that supervises *pid* (``hermes-serve.service``), or None.

    A ``.service`` cgroup alone only says where the process was started: a process launched by
    hand from a shell that itself runs under some unit (a CI runner agent, ``cron.service``, a
    tmux or IDE user service, the gateway's own terminal tool) sits in THAT unit's cgroup. The
    unit owns the backend only when its live ``MainPID`` is this PID; otherwise restarting it
    restarts an unrelated service and leaves the backend down. None when the PID isn't part of
    a service, ownership can't be proved, the file is unreadable, or off Linux.
    """
    for cg_path in _pid_unified_cgroup_entries(pid):
        if cg_path.endswith(".service"):
            svc_name = cg_path.rsplit("/", 1)[-1]
            if svc_name and _unit_main_pid_is(svc_name, cg_path, pid):
                return svc_name
    return None


def _unit_main_pid_is(svc_name: str, cgroup_path: str, pid: int) -> bool:
    """True when *svc_name*'s live ``MainPID`` is *pid* (read-only ``systemctl show``)."""
    scope = _extract_scope_from_cgroup(cgroup_path)
    scopes = {"user": [["--user"]], "system": [[]]}.get(scope or "", [[], ["--user"]])
    for scope_args in scopes:
        try:
            result = _run_probe(
                ["systemctl", *scope_args, "show", svc_name, "--property=MainPID", "--value"], timeout=10)
        except _SYSTEMCTL_ERRORS:
            continue
        if result.returncode == 0 and (result.stdout or "").strip() == str(pid):
            return True
    return False


def _extract_scope_from_cgroup(cgroup_entry: str) -> str | None:
    """``user`` / ``system`` from a cgroup path (``/user.slice/…`` vs ``/system.slice/…``), else None."""
    if "/system.slice/" in cgroup_entry:
        return "system"
    if "/user.slice/" in cgroup_entry:
        return "user"
    return None


def _get_pid_cgroup_path(pid: int) -> str | None:
    """The unified (``0::``) cgroup path from ``/proc/<pid>/cgroup``, or None."""
    return next(_pid_unified_cgroup_entries(pid), None)


def _systemd_owner_for_pid(pid: int) -> tuple[str, str | None] | None:
    """``(unit, scope)`` of the systemd unit whose live ``MainPID`` is *pid*; ``None`` when no unit
    provably owns it (see :func:`_get_systemd_service_for_pid`). Scope is ``user``/``system`` or
    ``None`` when the cgroup path does not say."""
    unit = _get_systemd_service_for_pid(pid)
    if unit is None:
        return None
    return unit, _extract_scope_from_cgroup(_get_pid_cgroup_path(pid) or "")


def _systemd_restart_commands(unit: str, scope: str | None) -> list[str]:
    """The command(s) that restart *unit* in its scope; both forms when the scope is unknown."""
    user_cmd, system_cmd = f"systemctl --user restart {unit}", f"sudo systemctl restart {unit}"
    return {"user": [user_cmd], "system": [system_cmd]}.get(scope or "", [user_cmd, system_cmd])


def _format_restart_commands(commands: list[str]) -> str:
    """Join restart commands as a user-facing hint: each backticked, separated by " or "."""
    return " or ".join(f"`{c}`" for c in commands)


# launchd plist directories that can supervise a legacy ``hermes dashboard`` / ``hermes serve``
# backend on macOS, with the launchctl domain their jobs load into (LaunchAgents: ``gui/<uid>`` or
# ``user/<uid>``, probed per label like the gateway helpers; LaunchDaemons: ``system``). Both
# LaunchAgents dirs are per-user domains, so they share the ``agent`` kind.
def _launchd_plist_dirs() -> list[tuple[str, Path]]:
    return [
        ("agent", Path.home() / "Library" / "LaunchAgents"),
        ("agent", Path("/Library/LaunchAgents")),
        ("daemon", Path("/Library/LaunchDaemons")),
    ]


def _loaded_launchd_backend_jobs(
    plist_dirs: list[tuple[str, Path]] | None = None,
) -> list[tuple[str, str, list[str], int | None]]:
    """``(domain, label, program_arguments, live_pid)`` for every LOADED launchd job whose
    ``ProgramArguments`` is a legacy ``hermes dashboard`` / ``hermes serve`` backend. macOS only
    (empty elsewhere). Reads the plists (unreadable/malformed ones are skipped) and asks
    ``launchctl print`` per candidate label — a job that is not loaded in any domain is not
    returned, so an operator's stale plist never claims a process."""
    if sys.platform != "darwin":
        return []
    import plistlib
    from xml.parsers.expat import ExpatError

    from hermes_cli.gateway import _launchd_print_service_pid
    uid = os.getuid()  # windows-footgun: ok — darwin-only branch
    jobs: list[tuple[str, str, list[str], int | None]] = []
    for kind, plist_dir in (plist_dirs if plist_dirs is not None else _launchd_plist_dirs()):
        try:
            plists = sorted(plist_dir.glob("*.plist"))
        except OSError:
            continue
        for plist_path in plists:
            try:
                with open(plist_path, "rb") as f:
                    data = plistlib.load(f)
            # ExpatError is NOT a ValueError: plistlib propagates it unwrapped for
            # XML that is not well-formed (e.g. a hand-edited plist with a raw
            # `&` in `ProgramArguments`), and one such operator file must skip —
            # not abort — the whole post-pull cleanup scan.
            except (OSError, ValueError, plistlib.InvalidFileException, ExpatError):
                continue
            if not isinstance(data, dict):
                continue
            label = str(data.get("Label") or "").strip()
            args = data.get("ProgramArguments")
            if not label or not isinstance(args, list) or not args:
                continue
            argv = [str(a) for a in args]
            if _parse_backend_runtime(" ".join(argv)) is None:
                continue
            domains = ("system",) if kind == "daemon" else (f"gui/{uid}", f"user/{uid}")
            for domain in domains:
                try:
                    loaded, live_pid = _launchd_print_service_pid(domain, label)
                except _SYSTEMCTL_ERRORS:
                    loaded, live_pid = False, None
                if loaded:
                    jobs.append((domain, label, argv, live_pid))
                    break
    return jobs


def _launchd_job_owning_backend(
    pid: int, cmdline: list[str] | None, jobs: list[tuple[str, str, list[str], int | None]],
    ancestors: list[int] | tuple[int, ...] = (),
) -> tuple[str, str, int | None] | None:
    """``(domain, label, live_pid)`` of the loaded launchd job that owns *pid*: launchd reports *pid*
    (or one of its *ancestors* — a plist may wrap the backend in ``/bin/sh -c …`` without ``exec``)
    as the job's live process, OR the process runs the job's ``ProgramArguments`` — a detached copy
    of a supervised backend (an earlier respawn) holds the port the job needs, and respawning it again
    would only re-create that conflict. ``--no-open`` is ignored on both sides: the respawn path adds
    it, so an earlier respawn's argv is the plist's plus that flag. None when no loaded job claims
    the process."""
    def _norm(argv: list[str]) -> list[str]:
        return [a for a in argv if a != "--no-open"]

    for domain, label, argv, live_pid in jobs:
        if live_pid is not None and (live_pid == pid or live_pid in ancestors):
            return (domain, label, live_pid)
        if cmdline is not None and _norm(list(cmdline)) == _norm(argv):
            return (domain, label, live_pid)
    return None
