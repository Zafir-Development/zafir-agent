"""The host-file read guard for a session's file references.

A persisted ``@image:``/``@file:`` reference only projects back to a ref when the file it names
still exists on THIS host and is something the agent could legitimately have read: a regular,
non-sensitive file within the inline attachment cap. Nothing here is served over HTTP — the
native session listener and TUI render a ref, or drop it.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from hermes_cli.home_data_layout import SECRET_CACHE_STORES
from hermes_constants import WEBAPP_ATTACHMENT_MAX_BYTES

# Bytes carried inline by a data URL: the attachment cap also bounds the base64 text and its
# decoded copy held in memory while verifying a stored image reference.
FS_DATA_URL_MAX_BYTES = WEBAPP_ATTACHMENT_MAX_BYTES

SANDBOX_NOT_FOUND = "File not found on the gateway host: the path may live inside the agent sandbox"

# Basenames the read guard must never read: credential stores that become live secrets the moment
# a session reference points at them. Mirrors the two canonical guards
# (agent.file_safety.get_read_block_error, gateway.platforms.base._ROOT_CREDENTIAL_FILES) so a
# projection never lags behind them.
_SENSITIVE_FILE_BASENAMES = frozenset({
    "auth.json", "auth.lock", "credentials", "config.yaml", ".anthropic_oauth.json",
    "google_token.json", "google_oauth_pending.json", "google_oauth.json",
    "webhook_subscriptions.json",
    *(Path(store).name for store in SECRET_CACHE_STORES),  # secret caches, Photon sidecar token
    ".git-credentials",  # git's credential-store cache (file_safety blocks it too)
})

# Directory names whose whole subtree is credential material (the canonical guards deny these as
# trees: _ROOT_CREDENTIAL_DIRS and the mcp-tokens/ prefix match). Match on ANY path component so
# the trees are blocked wherever they sit under the resolved path.
_SENSITIVE_DIR_NAMES = frozenset({"mcp-tokens", "pairing"})

# The canonical container roots: a host-side path there names a directory inside an agent
# sandbox, not this host, so "missing" gets the sandbox hint instead of a plain 404. The
# dashboard's configured-volume lookup is gone with the Files API; these two roots are static.
_CONTAINER_ROOTS = ("/workspace", "/root")


class HostFileRefused(RuntimeError):
    """A host path that is not a readable, non-sensitive regular file. ``str(exc)`` is the reason."""


def _is_sensitive_filename(name: str) -> bool:
    """Basename denylist: ``.env`` / ``.env.<suffix>`` / ``.envrc`` plus the credential-store
    basenames. Case-insensitive so ``.ENV`` / ``Auth.JSON`` on case-insensitive mounts can't slip
    past. Basename-only — call sites use :func:`is_sensitive_host_path`, which adds the
    credential-directory check."""
    lowered = name.lower()
    if lowered == ".env" or lowered.startswith(".env.") or lowered == ".envrc":
        return True
    return lowered in _SENSITIVE_FILE_BASENAMES


def is_sensitive_host_path(path: Path) -> bool:
    """True when the basename is sensitive OR any path component (case-insensitive) is a
    credential directory. Read-side guard, exactly as the deleted Files read routes applied it."""
    if _is_sensitive_filename(path.name):
        return True
    return any(part.lower() in _SENSITIVE_DIR_NAMES for part in path.parts)


def _sandbox_not_found_detail(path: Path) -> str:
    """Distinguish a path inside an agent sandbox from a plainly missing host file."""
    raw = path.as_posix()
    if any(raw == root or raw.startswith(root + "/") for root in _CONTAINER_ROOTS):
        return SANDBOX_NOT_FOUND
    return "File not found"


def resolve_host_path(raw_path: str) -> Path:
    """Resolve *raw_path* verbatim: no percent-decode fallback.

    The caller passes a path it already resolved once (a file URL decoded at the transport edge);
    decoding again would read the name ``report%2fsecret.txt`` as ``report/secret.txt``. Empty and
    NUL-bearing paths are refused, and a relative path resolves against the process cwd — the
    kept callers pass absolute paths by construction.
    """
    raw = str(raw_path or "").strip()
    if not raw:
        raise HostFileRefused("Path is required")
    if "\0" in raw:
        raise HostFileRefused("Invalid path")
    try:
        if os.name == "nt":
            # MEDIA links can reuse Git Bash paths; native Path would read /c/ as C:\c\.
            from tools.environments.local import _msys_to_windows_path

            raw = _msys_to_windows_path(raw)
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        raise HostFileRefused("Invalid path")


def regular_host_file(path: Path) -> tuple[Path, os.stat_result]:
    """Resolve *path* and vouch it is a readable, non-sensitive regular file on this host.

    Returns ``(resolved path, stat)``; raises :class:`HostFileRefused` otherwise."""
    target = resolve_host_path(str(path))
    try:
        st = target.stat()
    except (FileNotFoundError, NotADirectoryError):
        raise HostFileRefused(_sandbox_not_found_detail(target))
    except PermissionError:
        raise HostFileRefused("File is not readable")
    except OSError as exc:
        raise HostFileRefused(str(exc) or "Invalid path")
    if stat.S_ISDIR(st.st_mode):
        raise HostFileRefused("Path points to a directory")
    if not stat.S_ISREG(st.st_mode):
        raise HostFileRefused("Only regular files can be read")
    if is_sensitive_host_path(target):
        raise HostFileRefused("Access to sensitive files is not allowed")
    return target, st
