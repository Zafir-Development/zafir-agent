"""Every writer of ``.update_exit_code`` publishes it atomically.

The gateway /update watcher (gateway/run_notifications_update.py) polls ``.update_exit_code``
every 2 s from the gateway process and reads ``int(text or "1")``. A writer that truncates the
file in place left it empty for an instant; a poll landing there read exit 1, told the user the
update failed although it succeeded, and cleared the markers so no correction followed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.file_write_observer import observe_file_writes


def _watch(marker: Path) -> tuple[list[str], object]:
    """A gateway poll at every write instant: the marker's text whenever it exists."""
    seen: list[str] = []

    def poll() -> None:
        if marker.exists():
            seen.append(marker.read_text(encoding="utf-8-sig"))

    return seen, poll


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(path))
    return path


def test_fleet_writer_never_exposes_an_empty_exit_code(home):
    from hermes_cli.update_cmd_fleet import _write_gateway_update_exit_code

    marker = home / ".update_exit_code"
    seen, poll = _watch(marker)
    with observe_file_writes(poll):
        _write_gateway_update_exit_code(True)
    assert "" not in seen
    assert marker.read_text(encoding="utf-8").strip() == "0"


def test_completion_success_never_exposes_an_empty_exit_code(home):
    from hermes_cli.update_completion import _publish_gateway_success

    marker = home / ".update_exit_code"
    seen, poll = _watch(marker)
    with observe_file_writes(poll):
        _publish_gateway_success({"gateway_mode": True, "home": str(home)})
    assert "" not in seen
    assert marker.read_text(encoding="utf-8").strip() == "0"
