"""Legacy serve-backend support: managed-service restart (systemd/launchd/respawn), process discovery and update stdio hangup protection.

The ``hermes dashboard`` / ``hermes serve`` commands are gone; the updater still has to stop and
restart backends an older release left running (and every pre-PM updater resolves these names from
the frozen compat surface, ``tests/compat/old_updater_surface.json``). Nothing here serves a page.

Split out of ``hermes_cli/main.py``. Names that still live in main (``PROJECT_ROOT``, ...)
are imported lazily inside the functions that use them (avoids an import cycle).
"""

import contextlib
import os
import re
import shlex
import subprocess
import sys
import time

from pathlib import Path



def _find_stale_dashboard_pids(*, exclude_pids: set[int] | None = None,
                               scope_home: str | None = None) -> list[int]:
    """PIDs of running ``dashboard``/``serve`` backends the caller may stop.

    *scope_home*: keep only backends whose resolved Hermes home (see
    ``_hermes_home_for_pid``) is this home; unreadable ownership is spared, never guessed.
    ``--stop`` and the post-update cleanup pass their own home so another install's or
    profile's backend on the same machine is never a target (#113978).
    """
    from hermes_cli.dashboard_procs import (
        _caller_ancestor_pids,
        _is_caller_wrapper_shell,
        _pids_owned_by_hermes_home,
        _scan_dashboard_processes,
    )
    pids = [pid for pid, _cmd in _scan_dashboard_processes(exclude_pids=exclude_pids)]
    # The scan also selects the caller's own wrapper shell (``bash -c 'hermes dashboard --stop'``);
    # killing it takes down the invoking terminal.
    ancestors = _caller_ancestor_pids()
    pids = [pid for pid in pids if not _is_caller_wrapper_shell(pid, ancestors)]
    return _pids_owned_by_hermes_home(pids, scope_home) if scope_home else pids


def _parse_dashboard_runtime(command: str) -> tuple[str, str, int] | None:
    """Best-effort parse of a dashboard/server cmdline into mode, host, and port.

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




_DASHBOARD_SYSTEMD_UNIT = "hermes-dashboard.service"

_SYSTEMCTL_ERRORS = (FileNotFoundError, subprocess.TimeoutExpired, OSError)


def _run_probe(cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess:
    """Captured, text-decoded ``subprocess.run`` for short local probes (systemctl, ps)."""
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def _restart_managed_dashboard_service(reason: str, unit: str = _DASHBOARD_SYSTEMD_UNIT) -> bool:
    """Restart a systemd-managed dashboard instead of raw-killing its PID.

    True when a unit was found and handled (success or printed failure) — which
    deliberately stops the caller's ``os.kill`` fallback: systemd treats a direct
    SIGTERM as a clean stop, so ``Restart=on-failure`` won't bring it back.
    """
    if sys.platform == "win32":
        return False

    def _systemctl(*args: str, timeout: int = 10) -> subprocess.CompletedProcess:
        return _run_probe(["systemctl", *args], timeout=timeout)

    # User manager first (Hermes installs Linux services in the user scope by
    # default), system manager only when the unit isn't there. Keep the selected
    # scope for ALL probes and the restart — a user unit must never be restarted
    # through the system manager (or raw-killed).
    scope: tuple[str, ...] | None = None
    for candidate in (("--user",), ()):
        try:
            result = _systemctl(*candidate, "list-unit-files", unit, "--no-legend", "--no-pager")
        except _SYSTEMCTL_ERRORS:
            continue
        if result.returncode != 0:
            continue
        unit_rows = (result.stdout or "").splitlines()
        if any(row.split()[0:1] == [unit] for row in unit_rows if row.split()):
            scope = candidate
            break

    if scope is None:
        return False

    try:
        active = _systemctl(*scope, "is-active", unit)
        enabled = _systemctl(*scope, "is-enabled", unit)
    except _SYSTEMCTL_ERRORS:
        return False

    active_state = (active.stdout or "").strip()
    enabled_state = (enabled.stdout or "").strip()
    if active_state != "active" and enabled_state not in {
        "enabled", "enabled-runtime", "linked", "linked-runtime", "static", "generated",
    }:
        return False

    print(f"\n⟲ Restarting managed dashboard service ({reason})")

    scope_label = "systemctl --user" if scope else "sudo systemctl"
    commands = [("systemctl", *scope, "restart", unit)]
    if not scope:
        # System units may require privilege escalation; user units must use
        # the user manager directly and never prompt for sudo.
        commands.append(("sudo", "-n", "systemctl", "restart", unit))

    errors: list[str] = []
    for command in commands:
        try:
            result = _run_probe(list(command), timeout=60)
        except _SYSTEMCTL_ERRORS as e:
            errors.append(f"{' '.join(command)}: {e}")
            continue
        if result.returncode == 0:
            print(f"    ✓ restarted {unit}")
            return True
        errors.append(f"{' '.join(command)}: {(result.stderr or result.stdout or '').strip()}")

    print(f"    ✗ failed to restart {unit}")
    for err in errors:
        if err.strip():
            print(f"      {err}")
    print(
        "  Dashboard is managed by systemd; not raw-killing its PID because "
        "systemd would treat that as a clean stop."
    )
    print(f"  Restart manually: {scope_label} restart {unit}")
    return True


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

    A ``.service`` cgroup alone only says where the process was started: a dashboard launched by
    hand from a shell that itself runs under some unit (a CI runner agent, ``cron.service``, a
    tmux or IDE user service, the gateway's own terminal tool) sits in THAT unit's cgroup. The
    unit owns the backend only when its live ``MainPID`` is this PID; otherwise restarting it
    restarts an unrelated service and leaves the dashboard down. None when the PID isn't part of
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


def _try_restart_systemd_service(svc_name: str, cgroup_path: str | None = None) -> bool:
    """Restart *svc_name* via systemctl (``--user`` for user-scope units). True on success.

    Unknown scope tries system first, then user.
    """
    scope = _extract_scope_from_cgroup(cgroup_path) if cgroup_path else None
    system_cmd = ["systemctl", "restart", svc_name]
    user_cmd = ["systemctl", "--user", "restart", svc_name]
    candidates = {"user": [user_cmd], "system": [system_cmd]}.get(scope, [system_cmd, user_cmd])
    for cmd in candidates:
        try:
            if _run_probe(cmd, timeout=15).returncode == 0:
                return True
        except _SYSTEMCTL_ERRORS:
            continue
    return False


# launchd plist directories that can supervise a ``hermes dashboard`` / ``hermes serve`` backend on
# macOS, with the launchctl domain their jobs load into (LaunchAgents: ``gui/<uid>`` or ``user/<uid>``,
# probed per label like the gateway helpers; LaunchDaemons: ``system``). Both LaunchAgents dirs are
# per-user domains, so they share the ``agent`` kind.
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
    ``ProgramArguments`` is a ``hermes dashboard`` / ``hermes serve`` backend. macOS only (empty
    elsewhere). Reads the plists (unreadable/malformed ones are skipped) and asks ``launchctl print``
    per candidate label — a job that is not loaded in any domain is not returned, so an operator's
    stale plist never claims a process."""
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
            if _parse_dashboard_runtime(shlex.join(argv)) is None:
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


def _restart_launchd_job(domain: str, label: str, old_pid: int | None, *, timeout: float = 15.0) -> bool:
    """Bring a launchd-supervised backend back after its process was stopped: ``launchctl kickstart
    <domain>/<label>`` (no ``-k`` — a KeepAlive job may already have respawned it, and a kill would
    take that fresh process down), then require launchd to report a live PID other than *old_pid*
    within *timeout*. A kickstart that returns 0 only means "restart requested"; a job that is loaded
    but never comes back on a fresh PID is a failure the operator must hear about."""
    from hermes_cli.gateway import _wait_for_launchd_service_pid
    try:
        if _run_probe(["launchctl", "kickstart", f"{domain}/{label}"], timeout=30).returncode != 0:
            return False
        return _wait_for_launchd_service_pid(label, old_pid=old_pid, timeout=timeout, domain=domain)
    except _SYSTEMCTL_ERRORS:
        return False


def _dashboard_cmdline_for_pid(pid: int) -> list[str] | None:
    """Exact argv of a running process: ``/proc/<pid>/cmdline`` (Linux), ``ps -o command=`` + shlex
    (macOS), None on Windows (no graceful taskkill window; Desktop manages its backend)."""
    if sys.platform == "win32":
        return None
    try:
        cmdline_path = f"/proc/{pid}/cmdline"
        if os.path.exists(cmdline_path):
            with open(cmdline_path, "rb") as f:
                raw = f.read()
            argv = [part.decode("utf-8", errors="replace") for part in raw.split(b"\x00") if part]
            return argv or None
        result = _run_probe(["ps", "-p", str(pid), "-o", "command="], timeout=10)
        if result.returncode != 0:
            return None
        command = (result.stdout or "").strip()
        if not command:
            return None
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = command.split()
        return argv or None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


_RESPAWN_LIVENESS_GRACE_SECONDS = 1.0


def _respawnable_command_for_current_install(argv: list[str]) -> list[str]:
    """Rebuild a captured ``[<interpreter>, <hermes launcher>, ...]`` argv on this install's launcher.

    A pre-PM-takeover install left ``~/.local/bin/hermes`` as a symlink to a Python console
    script, so the kernel recorded a manual backend as ``[<old venv python>, <launcher>, dashboard,
    ...]``. The takeover then rewrote that launcher into a POSIX shell shim, and replaying the
    captured argv verbatim asks the old interpreter to parse a shell script (#124778). This
    checkout's own ``hermes`` entry script stays Python, so it and every other shape replay unchanged.
    """
    root = Path(__file__).resolve().parents[1]
    if (len(argv) > 2 and os.path.basename(argv[0]).startswith("python")
            and os.path.basename(argv[1]) == "hermes" and Path(argv[1]) != root / "hermes"):
        from hermes_cli._launchers import runtime_command
        return runtime_command(root, argv[2:])
    return list(argv)


def _respawn_dashboard_processes(commands: list[list[str]]) -> list[list[str]]:
    """Respawn manually-started dashboards after ``hermes update``, detached, logging to
    ``logs/dashboard-restart.log``; returns the argvs that failed to spawn. Callers pre-filter via
    ``_filter_dashboard_respawn_candidates`` (no Desktop ``--port 0`` backends, capped per profile).

    See #78821.
    """
    from hermes_constants import get_hermes_home
    respawned: list[list[str]] = []
    spawned: list[tuple[list[str], list[str], subprocess.Popen]] = []
    failed: list[tuple[list[str], list[str], str]] = []
    log_path = get_hermes_home() / "logs" / "dashboard-restart.log"
    with contextlib.suppress(OSError):
        log_path.parent.mkdir(parents=True, exist_ok=True)

    for original in commands:
        command = _respawnable_command_for_current_install(original)
        # Keep restarted dashboards headless; reopening a browser after a
        # background update is noisy and fails in SSH/headless sessions.
        if "dashboard" in command and "--no-open" not in command:
            command = [*command, "--no-open"]
        try:
            with open(log_path, "ab") as log_f:
                proc = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=log_f, stderr=subprocess.STDOUT,
                    # detached-spawn: ok — dashboard service launch, meant to outlive the CLI that starts it
                    start_new_session=True, close_fds=True)
            spawned.append((original, command, proc))
        except (OSError, ValueError) as exc:
            failed.append((original, command, str(exc)))

    # A respawned backend is a resident server: one that exits within the grace
    # window died at startup (SyntaxError on a stale argv, port already bound,
    # ...) and must surface as a failure, not as ``✓ restarted`` (#124778).
    if spawned:
        time.sleep(_RESPAWN_LIVENESS_GRACE_SECONDS)
    for original, command, proc in spawned:
        if proc.poll() is None:
            respawned.append(command)
        else:
            failed.append((original, command, f"child exited during the first "
                                              f"{_RESPAWN_LIVENESS_GRACE_SECONDS:.0f}s (code {proc.returncode})"))

    for command in respawned:
        print(f"    ✓ restarted: {shlex.join(command)}")
    for _, command, err_msg in failed:
        print(f"    ✗ failed to restart ({shlex.join(command)}): {err_msg}")
    # The caller's argv, not the spawned one: callers match it against the stopped PID's
    # captured cmdline to book the runtime as not brought back (#109290).
    return [original for original, _, _ in failed]


class _UpdateOutputStream:
    """stdout/stderr wrapper for ``hermes update``: mirrors to ``logs/update.log`` and, once the
    terminal vanishes (BrokenPipe/OSError/ValueError), drops screen output instead of the update."""

    _BROKEN = (BrokenPipeError, OSError, ValueError)

    def __init__(self, original, log_file):
        self._original = original
        self._log = log_file
        self._original_broken = False

    def write(self, data):
        # Mirror to the log file first — it's the most reliable destination.
        if self._log is not None:
            with contextlib.suppress(Exception):
                self._log.write(data)
        if not self._original_broken:
            try:
                return self._original.write(data)
            except self._BROKEN:
                self._original_broken = True  # terminal vanished; keep updating
        return len(data) if isinstance(data, (str, bytes)) else 0

    def flush(self):
        if self._log is not None:
            with contextlib.suppress(Exception):
                self._log.flush()
        if self._original_broken:
            return
        try:
            self._original.flush()
        except self._BROKEN:
            self._original_broken = True

    def isatty(self):
        if self._original_broken:
            return False
        try:
            return self._original.isatty()
        except Exception:
            return False

    def fileno(self):
        # Defer to the underlying stream; callers handle failures as when unwrapped.
        return self._original.fileno()

    def __getattr__(self, name):
        return getattr(self._original, name)


def _install_hangup_protection(gateway_mode: bool = False):
    """Protect ``cmd_update`` from SIGHUP (→ SIG_IGN, inherited by pip/git children) and broken pipes
    (stdio wrapped in ``_UpdateOutputStream``). SIGINT/SIGTERM are left alone — legitimate cancels.
    Gateway updates are already detached, but still need the log mirror for the
    Desktop progress watchdog. Returns state for ``_finalize_update_output``."""
    state = {
        "prev_stdout": sys.stdout, "prev_stderr": sys.stderr, "log_file": None, "installed": False}

    import signal as _signal

    if not gateway_mode and hasattr(_signal, "SIGHUP"):
        # Non-main thread: update still runs, just without hangup protection.
        with contextlib.suppress(ValueError, OSError):
            _signal.signal(_signal.SIGHUP, _signal.SIG_IGN)

    # Any failure here is non-fatal; we just skip the wrap.
    try:
        # Late-bound import so tests can monkeypatch it to simulate setup failure. The ROOT
        # home, never a sticky profile's: the update mutates the shared checkout, and the
        # Desktop and the hand-off scripts read <root>/logs/update.log.
        from hermes_constants import get_default_hermes_root as _get_root_home
        logs_dir = _get_root_home() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = open(logs_dir / "update.log", "a", buffering=1, encoding="utf-8")

        import datetime as _dt

        stage = "continued on the pulled code" if os.environ.get("HERMES_UPDATE_POST_SWAP") == "1" else "started"
        log_file.write(f"\n=== hermes update {stage} {_dt.datetime.now().isoformat(timespec='seconds')} ===\n")

        state["log_file"] = log_file
        sys.stdout = _UpdateOutputStream(state["prev_stdout"], log_file)
        sys.stderr = _UpdateOutputStream(state["prev_stderr"], log_file)
        state["installed"] = True
    except Exception:
        state["log_file"] = None

    return state


def _finalize_update_output(state):
    """Restore stdio and close the update.log handle opened by ``_install_hangup_protection``."""
    if not state:
        return
    if state.get("installed"):
        with contextlib.suppress(Exception):
            sys.stdout = state.get("prev_stdout", sys.stdout)
        with contextlib.suppress(Exception):
            sys.stderr = state.get("prev_stderr", sys.stderr)
    log_file = state.get("log_file")
    if log_file is not None:
        with contextlib.suppress(Exception):
            log_file.flush()
            log_file.close()


























