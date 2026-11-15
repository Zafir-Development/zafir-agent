"""Host-wide singleton rendezvous: one lock + one record per ROLE per OS user.

Multiplex-only (Teknium ruling): exactly ONE ``hermes gateway run`` per host, multiplexing
every profile. The per-``HERMES_HOME`` gateway lock/PID files
(``gateway.status``) cannot express that — N profiles are N homes, so N processes each take
their own flock and none of them ever sees the others. This module adds the missing layer:

* a **host lock** (flock/``msvcrt``) held for the lifetime of the winning process, and
* a **rendezvous record** the winner publishes so a second invocation can find it, prove it
  is the same live process, and ATTACH instead of binding a second port.

Both live in :func:`gateway.status._get_lock_dir` — the only cross-profile lock root already
in the tree (``$HERMES_GATEWAY_LOCK_DIR`` else ``$XDG_STATE_HOME/hermes/gateway-locks``),
which scopes to the **OS user**. That is the correct granularity: separate OS users have
separate ``$HOME``s, separate ``~/.hermes`` profile roots, separate ports-by-convention and
separate credentials, so "one per host" means "one per host per OS user".

**Staleness is proved, never assumed.** New records pair the PID with the repository's stable
process-start fingerprint (boot-relative on Linux/WSL); ``createTime`` remains the legacy fallback.
A dead PID or a mismatched process incarnation is STALE and ignored — an attaching client must
never dial a recycled PID's port.

**Relationship to ``spawn-ledger.json``** (``hermes_cli/process_identity.py``): the ledger stays
the append-only machine roster of every long-lived Hermes process and is still written
unchanged. It cannot be the host record: it has no lock, no
single-writer semantics, no removal on exit, and no place to publish a protocol version or
an authentication handle. The record here is authoritative for "who owns this host role"; the
ledger remains authoritative for "what is running". Both are written. New host records pair the
ledger's live-PID proof with ``gateway.status``'s canonical process-start fingerprint; legacy
records without that fingerprint keep the old ``(pid, create_time)`` proof.
"""

from __future__ import annotations

import contextlib
import enum
import hashlib
import json
import logging
import os
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, UTC
from pathlib import Path
from typing import Any, Optional, Sequence
from hermes_dir_acl import make_user_dir

from utils import atomic_json_write

logger = logging.getLogger(__name__)

#: Bumped when the record's shape or the attach handshake changes incompatibly. A reader that
#: does not recognise the version refuses to attach instead of guessing.
HOST_PROTOCOL_VERSION = 1

ROLE_GATEWAY = "gateway"
_ROLES = (ROLE_GATEWAY,)

# Open lock handles, keyed by (role, resolved lock path): the OS releases the flock when this
# process dies, which is what makes a crashed owner's host lock re-acquirable without a reaper.
# The PATH is part of the key because the lock dir is env-derived (HERMES_GATEWAY_LOCK_DIR):
# keyed by role alone, a second call after the dir changed returned "already held" without ever
# creating the new lock file, so owns_host_lock() lied and one pytest process leaked the handle
# across tests.
_lock_handles: dict[tuple[str, str], Any] = {}


@dataclass(frozen=True)
class HostRecord:
    """A published host-role owner. ``profiles`` is the SERVED set, not the launch profile."""

    role: str
    pid: int
    create_time: Optional[float]
    host: str
    port: Optional[int]
    protocol_version: int
    token_fingerprint: str
    profiles: tuple[str, ...]
    updated_at: str
    #: HERMES_HOME the owner was launched from. The attach channel (``gateway.control_socket``) is
    #: keyed by home, so without it a client can only guess the default root — wrong as soon as a
    #: named profile launches the host process. Absent in records written before this field; added
    #: WITHOUT a protocol bump on purpose, because a bump would make every live owner's record read
    #: as stale and a second gateway would start.
    home: str = ""
    #: Stable process-start fingerprint. On Linux/WSL this is boot-relative /proc start ticks,
    #: so a wall-clock resync cannot make a live owner look like a recycled PID. Optional for
    #: records written by older Hermes versions, which still fall back to create_time.
    #: NOT unique across reboots — pair it with ``boot_epoch``.
    start_time: Optional[int] = None
    #: Instantiation epoch (boot id + PID 1 start). Distinguishes a pre-reboot owner from an
    #: early-boot process that reused its PID and landed inside the start-tick drift tolerance.
    #: Absent on older records; added WITHOUT a protocol bump, because a bump would make every
    #: live owner's record read as stale and a second gateway would start.
    boot_epoch: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "home": self.home,
            "pid": self.pid,
            "createTime": self.create_time,
            "startTime": self.start_time,
            "bootEpoch": self.boot_epoch,
            "host": self.host,
            "port": self.port,
            "protocolVersion": self.protocol_version,
            "tokenFingerprint": self.token_fingerprint,
            "profiles": list(self.profiles),
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_json(cls, payload: Any) -> Optional[HostRecord]:
        if not isinstance(payload, dict):
            return None
        pid = payload.get("pid")
        role = payload.get("role")
        if not isinstance(pid, int) or pid <= 0 or role not in _ROLES:
            return None
        create = payload.get("createTime")
        start = payload.get("startTime")
        port = payload.get("port")
        profiles = payload.get("profiles")
        version = payload.get("protocolVersion")
        return cls(
            role=role,
            pid=pid,
            create_time=float(create) if isinstance(create, (int, float)) else None,
            start_time=(
                int(start)
                if isinstance(start, int) and not isinstance(start, bool) and start > 0
                else None
            ),
            boot_epoch=str(payload.get("bootEpoch") or ""),
            host=str(payload.get("host") or ""),
            port=int(port) if isinstance(port, int) and 0 < port <= 65535 else None,
            protocol_version=version if isinstance(version, int) else 0,
            token_fingerprint=str(payload.get("tokenFingerprint") or ""),
            profiles=tuple(str(p) for p in profiles if isinstance(p, str)) if isinstance(profiles, list) else (),
            updated_at=str(payload.get("updatedAt") or ""),
            home=str(payload.get("home") or ""),
        )


def host_state_dir() -> Path:
    """Per-OS-USER rendezvous dir (shared by every profile of this user)."""
    from gateway.status import _get_lock_dir

    return _get_lock_dir()


def ensure_host_state_dir() -> Path:
    """The rendezvous dir, created owner-only (``0o700``) and tightened if it is not.

    A bare ``mkdir`` under the common ``umask 002`` leaves the dir group-writable, and the record
    inside it is what every lifecycle verb believes: a same-group process could unlink+replace it
    and choose this host's ATTACH answers (which home to dial, which profiles are "served").
    Ownership of the dir is ours, so widening is repaired rather than refused.
    """
    directory = host_state_dir()
    make_user_dir(directory, parents=True, exist_ok=True, mode=0o700)
    if sys.platform != "win32":
        with contextlib.suppress(OSError):
            if stat.S_IMODE(directory.stat().st_mode) & 0o077:
                os.chmod(directory, 0o700)
    return directory


def _record_is_own(path: Path) -> bool:
    """True when ``path`` was written by THIS OS user inside a dir this user owns.

    ``read_record`` hands its result straight to :mod:`gateway.host_attach`, which dials the home
    it names and believes the served set it carries. A hand-written record therefore buys an
    attacker the lifecycle verdict for every profile on the host, so the file's ``st_uid`` — not
    its contents — is what makes it a record at all. Windows sets no ACLs from mode bits; there
    the dir already lives under the user's own state root.
    """
    if sys.platform == "win32":
        return True
    try:
        info = path.stat()
        parent = path.parent.stat()
    except OSError:
        return False
    uid = os.getuid()  # windows-footgun: ok — unreachable on Windows (early return above)
    if info.st_uid != uid or parent.st_uid != uid:
        logger.warning(
            "ignoring host record %s: owned by uid %s (expected %s)", path, info.st_uid, uid)
        return False
    return True


def _validated_role(role: str) -> str:
    if role not in _ROLES:
        raise ValueError(f"unknown host role: {role!r}")
    return role


def record_path(role: str) -> Path:
    return host_state_dir() / f"host-{_validated_role(role)}.json"


def lock_path(role: str) -> Path:
    return host_state_dir() / f"host-{_validated_role(role)}.lock"


def token_path(role: str) -> Path:
    return host_state_dir() / f"host-{_validated_role(role)}.token"


def token_fingerprint(token: str) -> str:
    """Short, non-reversible handle for a session token (safe to publish in the record)."""
    return hashlib.sha256(token.encode("utf-8", "replace")).hexdigest()[:16] if token else ""


def process_create_time(pid: Optional[int] = None) -> Optional[float]:
    """Creation time of ``pid`` (default: this process); ``None`` when unknowable."""
    from hermes_cli.process_identity import _process_create_time

    return _process_create_time(pid)


def _pid_incarnation_matches(pid: int, create_time: Optional[float]) -> Optional[bool]:
    """Reuse the spawn ledger's proof: True/False when provable, ``None`` when it cannot say."""
    from hermes_cli.process_identity import _pid_alive_matches

    return _pid_alive_matches(pid, create_time)


# A record published before ``bootEpoch`` existed cannot name its boot. Its ``createTime`` older
# than this boot's start (``psutil.boot_time()``, minus this slack) means EITHER a reboot (the
# owner is gone and its PID was recycled) OR a wall-clock step since the owner started (boot time
# is wall clock minus uptime, so a forward step moves it past a running owner's saved start;
# #117505). Clocks cannot tell those apart, so the host lock decides: a live gateway holds it.
_LEGACY_BOOT_SLACK_S = 120.0


def _boot_time() -> Optional[float]:
    try:
        import psutil

        return float(psutil.boot_time())
    except Exception:
        logger.debug("boot time unreadable; legacy record age check skipped", exc_info=True)
        return None


def _host_lock_is_free(role: str) -> Optional[bool]:
    """True when no process holds the host lock for ``role``; ``None`` when it cannot be probed.

    Read-only callers (status, dashboard) reach this, so it never creates the lock dir or file: a
    missing lock file means nobody holds the lock. The probe takes the lock for an instant, so a
    gateway claiming it in that instant gets HELD_BY_OTHER and its supervisor retries.
    """
    if owns_host_lock(role):
        return False
    from gateway.status import _probe_lock_file

    try:
        fd = os.open(str(lock_path(role)), os.O_RDWR)
    except FileNotFoundError:
        return True
    except OSError:
        logger.debug("host %s lock could not be probed", role, exc_info=True)
        return None
    return not _probe_lock_file(os.fdopen(fd, "r+", encoding="utf-8"))


def _current_boot_epoch() -> str:
    """Identity of this boot. Empty when /proc is unreadable — a recorded epoch is then unprovable."""
    try:
        from gateway.drain_control import current_instantiation_epoch

        return current_instantiation_epoch() or ""
    except Exception:
        logger.debug("boot epoch unreadable; host liveness will not use it", exc_info=True)
        return ""


def _record_incarnation_matches(record: HostRecord) -> Optional[bool]:
    """Whether the record still names the same live process incarnation.

    New records prefer the canonical start fingerprint: on Linux/WSL it comes from /proc start
    ticks and is immune to wall-clock shifts that move psutil.create_time(). Those ticks are
    NOT unique across reboots — they reset, and an early-boot PID reused within the drift
    tolerance looks like the dead owner. A published boot epoch that differs from this boot's is a
    mismatch; one that cannot be compared (this boot's epoch is unreadable) is unprovable, ``None``.

    A gateway record with no epoch (published before ``bootEpoch`` existed, or on any platform
    without /proc, where the epoch is always empty) whose create_time predates this boot is a
    mismatch only while nobody holds the host lock. A record with neither create_time nor
    start_time proves nothing about its pid, so it never vouches for one. Legacy records without
    a start fingerprint keep the create-time check. Do not infer identity from argv.
    """
    recorded_epoch = record.boot_epoch
    epoch = _current_boot_epoch()
    if recorded_epoch:
        if not epoch:
            return None  # boots can't be compared; matching ticks alone prove nothing
        if recorded_epoch != epoch:
            return False
    if record.start_time is None and record.create_time is None:
        return False
    if record.start_time is None:
        matched = _pid_incarnation_matches(record.pid, record.create_time)
    else:
        alive = _pid_incarnation_matches(record.pid, None)
        if alive is not True:
            return alive
        from gateway.status import get_process_start_time, start_time_fingerprints_match

        current = get_process_start_time(record.pid)
        matched = None if current is None else start_time_fingerprints_match(record.start_time, current)
    if matched is not True:
        return matched
    if record.role == ROLE_GATEWAY and not recorded_epoch and record.create_time is not None:
        boot = _boot_time()
        if boot is not None and record.create_time < boot - _LEGACY_BOOT_SLACK_S:
            lock_free = _host_lock_is_free(record.role)
            if lock_free is None:
                return None
            if lock_free:
                return False
    return True


def record_is_stale(record: Optional[HostRecord]) -> bool:
    """A record nobody may attach to: absent, unknown protocol, dead PID, or PID reuse.

    ``None`` from the liveness probe (no psutil, permission denied, an unexpected psutil error)
    means UNPROVABLE: the record is not reported stale, so a second process cannot bind a second
    port on a guess, and the attach path re-proves the owner before dialing it.
    """
    if record is None:
        return True
    if record.protocol_version != HOST_PROTOCOL_VERSION:
        return True
    return _record_incarnation_matches(record) is False


def liveness_is_proven(record: HostRecord) -> bool:
    """True only when the record's process-incarnation probe positively matched (never on ``None``).

    A record with neither ``createTime`` nor ``startTime`` cannot prove incarnation:
    ``_same_incarnation`` treats a missing create_time as a match, so a recycled pid would
    otherwise look alive forever. Topology already refused that shape; attach did not.
    """
    if record.create_time is None and record.start_time is None:
        return False
    return _record_incarnation_matches(record) is True


def dial_host(record: HostRecord) -> str:
    """Address to dial for ``record``: a wildcard bind is reached over loopback."""
    host = record.host or "127.0.0.1"
    return "127.0.0.1" if host in ("0.0.0.0", "::", "*", "") else host


def read_record(role: str, *, include_stale: bool = False) -> Optional[HostRecord]:
    """Published record for ``role``; ``None`` when absent, foreign, corrupt or (by default) stale."""
    path = record_path(role)
    if not _record_is_own(path):
        return None
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        record = HostRecord.from_json(json.loads(raw))
    except (ValueError, TypeError):
        return None
    if record is None:
        return None
    return record if include_stale or not record_is_stale(record) else None


def read_token(role: str) -> str:
    """Owner-written session token for ``role`` (``""`` when absent/unreadable).

    This is the handle an attaching client uses when the backend is auth-gated and therefore
    withholds its token from an unauthenticated ``GET /``. Confidentiality is enforced at WRITE
    time by :func:`hermes_cli.private_file.write_private_text` (POSIX ``0o600``; an
    owner+SYSTEM-only protected DACL on Windows, where mode bits set no ACLs at all). Reading it
    is therefore evidence of, not proof of, same-OS-user authority — the authority boundary the
    host lock is scoped to.
    """
    try:
        return token_path(role).read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def record_token_is_consistent(record: HostRecord) -> bool:
    """Does the on-disk token still hash to the record's fingerprint?

    A record published without a token (the gateway) has an empty fingerprint and is consistent
    by definition. A mismatch means the record and the token file come from different
    incarnations (a torn restart) — discovery must not attach with a token the owner rejects.
    """
    if not record.token_fingerprint:
        return True
    return token_fingerprint(read_token(record.role)) == record.token_fingerprint


class HostLockOutcome(enum.Enum):
    """Why a host-lock claim ended the way it did.

    ``COULD_NOT_OPEN`` is NOT contention: a read-only/undeletable lock dir (EROFS, EACCES,
    ENOSPC) collapsed into the same "another owner holds it" log and sent operators hunting a
    second gateway that never existed.
    """

    ACQUIRED = "acquired"
    HELD_BY_OTHER = "held-by-other"
    COULD_NOT_OPEN = "could-not-open"


def _lock_key(role: str) -> tuple[str, str]:
    path = lock_path(role)
    with contextlib.suppress(OSError):
        return (role, os.path.abspath(str(path)))
    return (role, str(path))


def claim_host_lock(role: str) -> tuple[HostLockOutcome, Optional[OSError]]:
    """Take the host-wide lock for ``role``. Idempotent per (role, lock path).

    Returns the outcome and, for ``COULD_NOT_OPEN``, the OSError that explains it.
    """
    role = _validated_role(role)
    key = _lock_key(role)
    if _lock_handles.get(key) is not None:
        return (HostLockOutcome.ACQUIRED, None)
    from gateway.status import _try_acquire_file_lock

    path = Path(key[1])
    try:
        ensure_host_state_dir()
        handle = open(path, "a+", encoding="utf-8")
    except OSError as exc:
        logger.debug("host %s lock could not be opened at %s", role, path, exc_info=True)
        return (HostLockOutcome.COULD_NOT_OPEN, exc)
    if not _try_acquire_file_lock(handle):
        with contextlib.suppress(OSError):
            handle.close()
        return (HostLockOutcome.HELD_BY_OTHER, None)
    _lock_handles[key] = handle
    return (HostLockOutcome.ACQUIRED, None)


def release_host_lock(role: str) -> None:
    """Release the host lock for ``role`` when this process holds it."""
    handle = _lock_handles.pop(_lock_key(_validated_role(role)), None)
    if handle is None:
        return
    from gateway.status import _release_file_lock

    _release_file_lock(handle)
    with contextlib.suppress(OSError):
        handle.close()


def owns_host_lock(role: str) -> bool:
    """True when THIS process holds the host lock for ``role`` (re-probing our own flock lies)."""
    return _lock_handles.get(_lock_key(_validated_role(role))) is not None


def host_lock_is_held(role: str) -> Optional[bool]:
    """Whether any process currently holds the host lock for ``role``.

    ``True`` / ``False`` when the flock can be observed; ``None`` when the lock file cannot
    be opened. Never retains a lock. This process's handle is authoritative: re-probing our
    own flock succeeds on POSIX, so a second open would lie.
    """
    role = _validated_role(role)
    if owns_host_lock(role):
        return True
    path = lock_path(role)
    if not path.exists():
        return False
    try:
        handle = open(path, "a+", encoding="utf-8")
    except OSError:
        return None
    from gateway.status import _probe_lock_file

    return _probe_lock_file(handle)


def record_names_live_owner(record: HostRecord) -> bool:
    """True when ``record``'s incarnation is proven AND its host lock is not observed free.

    The publisher holds the host lock for its whole life and the OS drops it on death, so a free
    flock falsifies a record whose pid merely looks alive (recycle, start-tick collision after a
    reboot — #138343, #133744). Every reader that trusts a record as a running owner uses this.
    """
    if not liveness_is_proven(record):
        return False
    if host_lock_is_held(record.role) is False:
        logger.debug("host %s record names pid %s but the host lock is free", record.role, record.pid)
        return False
    return True


def publish_record(
    role: str,
    *,
    host: str = "",
    port: Optional[int] = None,
    profiles: Sequence[str] = (),
    token: Optional[str] = None,
    home: str = "",
) -> Optional[HostRecord]:
    """Publish this process as the host owner of ``role``. ``None`` when the write failed.

    ``token`` (serve) is persisted 0600 next to the record and only its fingerprint is published.
    ``home`` is the launch HERMES_HOME — the key an attaching client needs to reach this owner's
    control socket.
    """
    role = _validated_role(role)
    from gateway.status import get_process_start_time

    record = HostRecord(
        role=role,
        pid=os.getpid(),
        create_time=process_create_time(),
        start_time=get_process_start_time(os.getpid()),
        boot_epoch=_current_boot_epoch(),
        host=str(host or ""),
        port=int(port) if isinstance(port, int) and port > 0 else None,
        protocol_version=HOST_PROTOCOL_VERSION,
        token_fingerprint=token_fingerprint(token or ""),
        profiles=tuple(str(p) for p in profiles),
        updated_at=datetime.now(UTC).isoformat(),
        home=str(home or ""),
    )
    try:
        ensure_host_state_dir()
        if token:
            # No record without its token: publishing one an attaching client cannot
            # authenticate against would degrade to a silent "attach refused forever".
            from hermes_cli.private_file import write_private_text

            write_private_text(token_path(role), token)
        atomic_json_write(record_path(role), record.to_json(), mode=0o600)
    except OSError:
        logger.warning("host %s record could not be published; discovery will not find it", role, exc_info=True)
        return None
    _invalidate_attach_cache()
    return record


def _invalidate_attach_cache() -> None:
    """Drop :mod:`gateway.host_attach`'s memo: the record it summarises just changed."""
    with contextlib.suppress(Exception):
        from gateway.host_attach import invalidate_host_gateway_cache

        invalidate_host_gateway_cache()


def discard_dead_record(role: str) -> bool:
    """Retract the record for ``role`` when its owner is provably gone; True when one was removed.

    A confirmed stop must retract the record too. Leaving it made ``gateway restart --all`` a
    silent no-op: the re-entered ``gateway run`` read the corpse's record, decided ATTACH and
    exited 0, so the host ended up with no gateway at all.
    """
    role = _validated_role(role)
    record = read_record(role, include_stale=True)
    if record is None:
        return False
    guard = None
    if record.pid != os.getpid() and _record_incarnation_matches(record) is not False:
        # A recycled pid can still look like the same incarnation. The publisher holds the
        # host lock for its life, so winning it proves the recorded owner is gone. Hold it
        # across the re-read and unlink: a free-lock probe released first let a new gateway
        # claim and publish in the gap, and we deleted ITS record and token. A private handle,
        # not claim_host_lock: cleanup must not enter this process's own claim/release ledger.
        if owns_host_lock(role) or (guard := _hold_lock_briefly(role)) is None:
            return False
    try:
        if guard is not None and read_record(role, include_stale=True) is None:
            return False
        for path in (record_path(role), token_path(role)):
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
    finally:
        if guard is not None:
            from gateway.status import _release_file_lock

            _release_file_lock(guard)
            with contextlib.suppress(OSError):
                guard.close()
    _invalidate_attach_cache()
    return True


def _hold_lock_briefly(role: str):
    """Open and flock ``role``'s host lock without registering it; ``None`` when not won."""
    from gateway.status import _try_acquire_file_lock

    path = lock_path(role)
    try:
        handle = open(path, "a+", encoding="utf-8")
    except OSError:
        return None
    if _try_acquire_file_lock(handle):
        return handle
    with contextlib.suppress(OSError):
        handle.close()
    return None


def clear_record(role: str) -> None:
    """Remove this process's record + token on exit (never another owner's)."""
    role = _validated_role(role)
    existing = read_record(role, include_stale=True)
    if existing is not None and existing.pid != os.getpid():
        return
    for path in (record_path(role), token_path(role)):
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
    _invalidate_attach_cache()


# Roles this process must clean up on the way out, and the signal handlers we prepended.
_cleanup_roles: list[str] = []
_prev_signal_handlers: dict[int, Any] = {}


def _cleanup_role(role: str) -> None:
    with contextlib.suppress(Exception):
        clear_record(role)
    with contextlib.suppress(Exception):
        release_host_lock(role)


def _handle_terminating_signal(signum, frame) -> None:
    """Drop the record + token, then hand off to the handler we prepended to."""
    import signal as _signal

    for role in tuple(_cleanup_roles):
        _cleanup_role(role)
    prev = _prev_signal_handlers.get(signum)
    if callable(prev):
        prev(signum, frame)
        return
    if prev is _signal.SIG_IGN:
        return
    with contextlib.suppress(Exception):
        _signal.signal(signum, _signal.SIG_DFL)
        os.kill(os.getpid(), signum)
    raise SystemExit(128 + int(signum))


def cleanup_on_exit(role: str) -> None:
    """Clear ``role``'s record + token and release its lock on exit — SIGTERM included.

    ``atexit`` alone is false advertising for the NORMAL stop: systemd stop, ``docker stop`` and
    the update relaunch all send SIGTERM, and every terminating SIGTERM path here ends in the
    default disposition (uvicorn's ``capture_signals`` re-raises it after its graceful shutdown),
    which kills the process without running ``atexit``. The record then outlived its process and
    the 0600 token kept a LIVE session token on disk indefinitely.

    The handler only PREPENDS cleanup: whatever handler was installed before (uvicorn's graceful
    shutdown, the exit-flush chain, a supervisor's) still runs, so the shutdown sequence is
    unchanged.
    """
    import atexit
    import signal as _signal
    import threading

    role = _validated_role(role)
    if role not in _cleanup_roles:
        _cleanup_roles.append(role)
        atexit.register(_cleanup_role, role)
    if threading.current_thread() is not threading.main_thread():
        return
    for name in ("SIGTERM", "SIGBREAK"):
        signum = getattr(_signal, name, None)
        if signum is None or signum in _prev_signal_handlers:
            continue
        with contextlib.suppress(ValueError, OSError, RuntimeError):
            prev = _signal.getsignal(signum)
            _signal.signal(signum, _handle_terminating_signal)
            _prev_signal_handlers[signum] = prev


def _multiplex_profiles_enabled() -> bool:
    """Will THIS process multiplex? An explicit ``true`` and an unset key both say yes, and an
    explicit ``false`` is RETIRED (``hermes_cli.gateway_multiplex_mode``) — it is warned about and
    ignored at boot, so it must not make the claim-time record advertise a narrower roster than
    the process actually serves. Reading it here was the last place the retired flag still decided
    topology, and it made CLI/dashboard report "standalone, serving default" while the runtime
    multiplexed. The RUNTIME verdict (a boot-time guard refusal) narrows the record afterwards, in
    ``gateway.run._refresh_host_gateway_record``, which republishes the SETTLED set.
    """
    return True


def served_profiles(*, multiplex: Optional[bool] = None) -> tuple[str, ...]:
    """Profiles this process multiplexes; ``()`` when the roster cannot be read.

    ``multiplex`` defaults to what this process's own config says. Hard-coding ``True`` here
    published a record claiming EVERY profile from a gateway that would only ever serve its own,
    and a second profile's supervised unit then stood down against a set nobody serves.
    """
    try:
        from hermes_cli.profiles import profiles_to_serve

        enabled = _multiplex_profiles_enabled() if multiplex is None else bool(multiplex)
        return tuple(name for name, _ in profiles_to_serve(multiplex=enabled))
    except Exception:
        logger.debug("served profile roster unavailable", exc_info=True)
        return ()


def describe(record: HostRecord) -> str:
    """One-line human description used by attach messages and conflict logs."""
    where = f"{record.host or '127.0.0.1'}:{record.port}" if record.port else "no bound port"
    profiles = ", ".join(record.profiles) if record.profiles else "unknown"
    return f"PID {record.pid} ({where}; profiles: {profiles})"
