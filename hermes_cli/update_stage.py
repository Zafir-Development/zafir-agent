"""Report a running update stage to an external progress UI, if one is watching.

An updater launcher may render progress from a status JSON file while it runs the update as a
child. Its own steps write stages it gates on; the PM sync / build stages this process drives can
run for minutes with nothing on screen. These helpers publish through the same file so a watching
window keeps moving.

Two discovery paths, because the status file's name embeds the launcher's pid:

- ``HERMES_UPDATE_STATUS_FILE``: exported by a launcher that knows its own path.
- Marker fallback: a launcher that predates the env var never exports the path, but it owns the
  update marker whose first line is its pid, and its status file is deterministic:
  ``${TMPDIR:-/tmp}/hermes-update-status.<pid>``.

Stdlib-only (importable under ``-I -S -B``) and never raises: a missing/stale/unwritable file means
no UI, and a progress hiccup must never fail an update.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

STATUS_FILE_ENV = "HERMES_UPDATE_STATUS_FILE"
MARKER_NAME = ".hermes-update-in-progress"


def _process_home() -> Path:
    """The marker and the shim's log live in the PROCESS home (update_lock.update_marker_path):
    the shim resolved ``$HERMES_HOME`` or the platform default, never a profile override, and
    the platform default (sudo invoker, data-dir suffix) is not ``~/.hermes`` everywhere."""
    from hermes_constants import get_process_hermes_home
    return get_process_hermes_home()


def status_file() -> Path | None:
    """The watching shim's status file, or None when no UI is discoverable."""
    exported = os.environ.get(STATUS_FILE_ENV, "").strip()
    if exported:
        return Path(exported)
    return _status_from_marker()


def _status_from_marker() -> Path | None:
    """Derive the shim's status file from the update marker's owner pid.

    The marker's first line is the hand-off shim's ``$$`` (update_lock.py
    adopts rather than rewrites it, so it still names the shim here). The
    shim's status file lives beside it, pid-suffixed. No marker (plain CLI
    update) or no matching file → no UI.
    """
    try:
        pid = int((_process_home() / MARKER_NAME).read_text(encoding="utf-8-sig")
                  .splitlines()[0].strip())
    except (OSError, ValueError, IndexError):
        return None
    if pid <= 0:
        return None
    # The shim writes beside ${TMPDIR:-/tmp}; gettempdir() resolves the same way.
    candidate = Path(tempfile.gettempdir()) / f"hermes-update-status.{pid}"
    return candidate if candidate.is_file() else None


def publish_stage(message: str) -> None:
    """Report a running stage to the watching UI. Best-effort, never raises.

    Only ever writes ``status=running``: terminal states belong to the watching
    launcher, which publishes them after this process has exited. The atomic replace mirrors the
    launcher's write_status — a polling reader must never observe a half-written file.
    """
    path = status_file()
    if path is None:
        return
    payload = json.dumps({"status": "running", "message": message})
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".update-stage-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except OSError:
        pass
