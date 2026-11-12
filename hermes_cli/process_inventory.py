"""Read-only process discovery shared by the gateway and the update pipeline.

Resolves a foreign process's Hermes home and parent chain from its exec-time environment,
``/proc`` and ``ps``. Every probe is best-effort: unreadable data returns ``None`` (or an empty
chain), never a guess, because callers use these answers to decide which process a stop may take.
"""

import contextlib
import os
import subprocess
import sys
from pathlib import Path

_PS_RUN_KWARGS = dict(capture_output=True, text=True, encoding="utf-8", errors="replace")


def _pid_environ(pid: int) -> dict[str, str] | None:
    """Exec-time environment of *pid* (psutil, then /proc); ``None`` when unreadable."""
    with contextlib.suppress(Exception):
        import psutil
        return dict(psutil.Process(pid).environ())
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return None
    env: dict[str, str] = {}
    for part in raw.split(b"\x00"):
        key, sep, value = part.partition(b"=")
        if sep:
            env[key.decode("utf-8", errors="replace")] = value.decode("utf-8", errors="replace")
    return env


def _pid_passwd_home(pid: int) -> str | None:
    """Login home of the user *pid* runs as, from the password database (psutil, then /proc).

    A service unit with a scrubbed environment exports no ``HOME``; the target resolves its own
    default home through ``Path.home()``, which falls back to this entry. The inspecting process's
    home belongs to a different user and must never stand in for it. ``None`` when the owner or the
    entry is unreadable, leaving the caller its existing fallback.
    """
    uid: int | None = None
    with contextlib.suppress(Exception):
        import psutil
        uid = psutil.Process(pid).uids().real
    if uid is None:
        with contextlib.suppress(OSError):
            uid = os.stat(f"/proc/{pid}").st_uid
    if uid is None:
        return None
    with contextlib.suppress(Exception):
        import pwd
        return pwd.getpwuid(uid).pw_dir or None
    return None


def _profile_flag_value(argv: list[str]) -> str | None:
    """Value of the first ``--profile X`` / ``-p X`` / ``--profile=X`` in *argv*."""
    for i, tok in enumerate(argv):
        if tok in ("--profile", "-p") and i + 1 < len(argv):
            return str(argv[i + 1])
        if tok.startswith("--profile="):
            return tok.split("=", 1)[1]
    return None


def _process_cmdline_for_pid(pid: int) -> list[str] | None:
    """Exact argv of a running process: ``/proc/<pid>/cmdline`` (Linux), ``ps -o command=`` + shlex
    (macOS), None on Windows (no ``/proc``; callers fall back to psutil)."""
    if sys.platform == "win32":
        return None
    try:
        cmdline_path = f"/proc/{pid}/cmdline"
        if os.path.exists(cmdline_path):
            with open(cmdline_path, "rb") as f:
                raw = f.read()
            argv = [part.decode("utf-8", errors="replace") for part in raw.split(b"\x00") if part]
            return argv or None
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="], timeout=10, **_PS_RUN_KWARGS, check=False)
        if result.returncode != 0:
            return None
        command = (result.stdout or "").strip()
        if not command:
            return None
        try:
            import shlex
            argv = shlex.split(command)
        except ValueError:
            argv = command.split()
        return argv or None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _hermes_home_for_pid(pid: int, *, require_launch_identity: bool = False) -> str | None:
    """Resolve a process home for discovery, or require pinned launch identity for termination.

    By default, ``None`` means an unreadable environment (another user, hardened ``/proc``).
    ``require_launch_identity`` also refuses missing argv, relative/missing home anchors and
    any profile selection that would depend on today's sticky ``active_profile``.

    A readable environment always resolves, replaying ``_apply_profile_override`` on the target's
    exec-time env + argv (``hermes -p X ...`` rewrites ``HERMES_HOME`` in ``os.environ`` AFTER
    startup, which ``/proc/<pid>/environ`` never reflects): a profile-shaped ``HERMES_HOME``
    without a flag is the home; otherwise the root is ``HERMES_HOME`` (its grandparent when
    profile-shaped) or the platform default of the process's own ``HOME`` / ``LOCALAPPDATA``
    (its owner's password-database home when a scrubbed unit environment exports neither), and
    the profile is the ``--profile``/``-p`` flag, else the root's sticky ``active_profile`` unless
    the process has a fixed identity (supervised child, gateway profile pin).
    """
    # Destructive callers require launch evidence; discovery may still use sticky selection.
    env = _pid_environ(pid)
    if env is None:
        return None
    from hermes_cli.profiles import get_active_profile, normalize_profile_name, profile_root_for_env_home
    argv = _process_cmdline_for_pid(pid)
    if require_launch_identity and argv is None:
        # The /proc/ps reader has no Windows implementation; psutil does.
        import psutil
        argv = psutil.Process(pid).cmdline()
    if require_launch_identity and not argv:
        return None
    argv = argv or []
    env_home = env.get("HERMES_HOME", "").strip()
    profile = _profile_flag_value(argv)
    if require_launch_identity:
        anchor = (env.get('LOCALAPPDATA') or env.get('USERPROFILE')) if sys.platform == 'win32' else env.get('HOME')
        if env_home and not Path(env_home).is_absolute():
            return None
        if not env_home and (not anchor or not Path(anchor).is_absolute()):
            return None
    if profile is None and env_home and Path(env_home).parent.name == "profiles":
        return env_home
    if sys.platform == "win32":
        local_appdata = env.get("LOCALAPPDATA", "").strip()
        base = Path(local_appdata) if local_appdata else Path(env.get("USERPROFILE") or Path.home()) / "AppData" / "Local"
        default_home = base / "hermes"
    else:
        default_home = Path(env.get("HOME") or _pid_passwd_home(pid) or Path.home()) / ".hermes"
    root = profile_root_for_env_home(env_home, default_home)
    fixed_identity = any(env.get(k) for k in ("HERMES_SUPERVISED_CHILD", "HERMES_S6_SUPERVISED_CHILD",
                                               "HERMES_GATEWAY_EXTERNAL_SUPERVISOR",
                                               "HERMES_GATEWAY_PROFILE_PIN"))
    if profile is None and not fixed_identity:
        if require_launch_identity:
            return None  # The sticky profile at launch is unknowable; never read today's value.
        profile = get_active_profile(root)
    canon = normalize_profile_name(profile) if profile else "default"
    return str(root) if canon == "default" else str(root / "profiles" / canon)


def _resolved_home(home: str) -> Path:
    try:
        return Path(home).resolve()
    except (OSError, RuntimeError, ValueError):
        return Path(home)


def _normalized_home_for_compare(home: str) -> str:
    """Install-identity key for *home*: symlinked / differently-spelled roots compare equal.

    See #94030.
    """
    return os.path.normcase(str(_resolved_home(home)))


def _process_ppid(pid: int) -> int | None:
    """Best-effort parent pid; None on failure (always None on Windows: no ``ps``)."""
    try:
        if sys.platform == "win32":
            return None
        result = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], timeout=5, **_PS_RUN_KWARGS, check=False)
        if result.returncode != 0 or not result.stdout:
            return None
        return int(result.stdout.strip().split()[0])
    except (ValueError, FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _process_ancestors(pid: int, *, max_depth: int = 8) -> list[int]:
    """Parent chain of *pid* (nearest first), stopping at init / a lookup failure / *max_depth*."""
    chain: list[int] = []
    current = pid
    while len(chain) < max_depth:
        parent = _process_ppid(current)
        if parent is None or parent <= 1 or parent == pid or parent in chain:
            break
        chain.append(parent)
        current = parent
    return chain


def _process_age_seconds(pid: int) -> float:
    """Process age from psutil's cross-platform start timestamp."""
    import time as _time

    import psutil as _psutil
    return max(0.0, _time.time() - _psutil.Process(pid).create_time())
