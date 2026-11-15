"""Regression tests: debug share captures update.log.

A failed update stores its root cause in ``logs/update.log`` (the full
stdout/stderr mirror of ``hermes update``). The updater's failure message
points users at ``hermes debug share``, so the share must carry that file
or update-failure reports arrive with zero root-cause signal (#100874).

These tests fail against the pre-fix capture set.
"""

import pytest

# The line shape the writer really produces (main.py _UpdateOutputStream mirror).
UPDATE_LOG_BODY = (
    "=== hermes update started 2026-09-02T03:21:09 ===\n"
    "→ Fetching updates...\n"
    "→ Building the TUI...\n"
    "✗ TUI build failed\n"
)


@pytest.fixture
def home_with_update_logs(tmp_path, monkeypatch):
    """Isolated HERMES_HOME whose logs directory holds update.log."""
    home = tmp_path / "hermes_test_home"
    logs = home / "logs"
    logs.mkdir(parents=True)
    (logs / "agent.log").write_text(
        "2026-09-02 03:21:00 INFO agent.conversation_loop: API call #1\n"
    )
    (logs / "update.log").write_text(UPDATE_LOG_BODY)
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


@pytest.fixture
def home_without_update_logs(tmp_path, monkeypatch):
    """Isolated HERMES_HOME with only the always-on logs present."""
    home = tmp_path / "hermes_test_home"
    logs = home / "logs"
    logs.mkdir(parents=True)
    for name in ("agent.log", "errors.log", "gateway.log"):
        (logs / name).write_text("2026-09-02 03:21:00 INFO x: one line\n")
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


class TestCaptureDefaultLogSnapshots:
    """The snapshot collector must include the update log."""

    def test_snapshots_include_the_update_key(self, home_with_update_logs):
        from hermes_cli.debug import _capture_default_log_snapshots

        snaps = _capture_default_log_snapshots(100)

        assert "update" in snaps
        assert "TUI build failed" in snaps["update"].tail_text

    def test_snapshots_read_the_root_home_update_log_under_a_profile(self, tmp_path, monkeypatch):
        """``hermes update`` writes the ROOT home's log, whatever profile is active."""
        from hermes_cli.debug import _capture_default_log_snapshots

        root = tmp_path / "root"
        profile = root / "profiles" / "coder"
        (root / "logs").mkdir(parents=True)
        (profile / "logs").mkdir(parents=True)
        (root / "logs" / "update.log").write_text(UPDATE_LOG_BODY)
        monkeypatch.setenv("HERMES_HOME", str(profile))

        snaps = _capture_default_log_snapshots(100)

        assert "TUI build failed" in snaps["update"].tail_text

    def test_missing_file_reports_absence_without_raising(self, home_without_update_logs):
        """A fresh install has no update log — capture degrades, not crashes."""
        from hermes_cli.debug import _capture_default_log_snapshots

        snaps = _capture_default_log_snapshots(100)

        assert "update" in snaps
        assert "not found" in snaps["update"].tail_text


class TestCollectDebugReport:
    """The summary report (what users paste) shows the update tail."""

    def test_report_contains_the_update_section(self, home_with_update_logs):
        from hermes_cli.debug import collect_debug_report

        report = collect_debug_report(log_lines=50, dump_text="dump")

        assert "--- update.log" in report
        assert "TUI build failed" in report

    def test_report_keeps_the_section_when_the_log_is_absent(self, home_without_update_logs):
        from hermes_cli.debug import collect_debug_report

        report = collect_debug_report(log_lines=50, dump_text="dump")

        assert "--- agent.log" in report
        assert "--- update.log" in report


class TestCollectShareBundle:
    """The upload bundle (paste.rs + --nous) carries the full update log."""

    def test_bundle_includes_the_update_log_when_present(self, home_with_update_logs):
        from hermes_cli.debug import collect_share_bundle

        bundle = collect_share_bundle(log_lines=50, redact=False)

        assert "update.log" in bundle
        assert "TUI build failed" in bundle["update.log"]
        assert "--- full update.log ---" in bundle["update.log"]

    def test_bundle_omits_the_update_key_when_the_file_is_absent(self, home_without_update_logs):
        from hermes_cli.debug import collect_share_bundle

        bundle = collect_share_bundle(log_lines=50, redact=False)

        assert "update.log" not in bundle
        assert "agent.log" in bundle


class TestLogsRegistry:
    """LOG_FILES has a readable key for the file `hermes logs list` already shows."""

    def test_update_key_resolves_the_real_filename(self):
        from hermes_cli.logs import LOG_FILES

        assert LOG_FILES.get("update") == "update.log"

    def test_tail_log_reads_update_log_from_hermes_home(self, home_with_update_logs):
        """End-to-end: `hermes logs update` resolves and prints the file."""
        from hermes_cli import logs as logs_mod

        logs_mod.tail_log("update", num_lines=10)

    def test_tail_log_names_the_update_log_when_unknown_requested(self, home_with_update_logs, capsys):
        from hermes_cli import logs as logs_mod

        with pytest.raises(SystemExit) as excinfo:
            logs_mod.tail_log("no-such-log")

        assert excinfo.value.code == 1
        hint = capsys.readouterr().out
        assert "update" in hint
