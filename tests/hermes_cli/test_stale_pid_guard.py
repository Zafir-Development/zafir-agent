"""Regression tests for the fail-closed PID-ownership guard.

Refs #90471 / #89614.  The shared Windows ``taskkill`` boundary
(``hermes_cli/_subprocess_compat.pid_is_hermes`` / ``kill_process_tree``).

Acceptance from #90471:
1. missing / unreadable / non-matching identity fails closed -> no taskkill
2. a recycled or foreign PID control process remains untouched
3. probe failure or timeout is never converted into permission to kill
"""
from pathlib import Path
from unittest import mock

import pytest

from hermes_cli import _subprocess_compat
from hermes_cli import process_inventory


def _probe_stdout(value: str) -> mock.Mock:
    return mock.Mock(stdout=value)


class TestPidIsHermes:
    """The shared identity probe must fail closed on every ambiguity."""

    def test_non_windows_is_unconditional_pass(self):
        # Non-Windows callers have no taskkill path at all.
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", False):
            assert _subprocess_compat.pid_is_hermes(1234) is True

    def test_non_windows_still_rejects_recycled_identity(self):
        # An explicit fingerprint mismatch is a recycled PID on any platform.
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", False), mock.patch.object(
            _subprocess_compat, "_process_start_time", return_value=456
        ):
            assert _subprocess_compat.pid_is_hermes(
                1234, expected_start_time=123
            ) is False

    def test_hermes_match_requires_token_boundary(self):
        # "hermes" buried inside an unrelated path segment must not match.
        assert _subprocess_compat._text_names_hermes(
            r"c:\users\shermesa\app.exe"
        ) is False
        assert _subprocess_compat._text_names_hermes(
            r"C:\Users\x\.hermes-runtime\python.exe -m hermes_cli.main"
        ) is True
        assert _subprocess_compat._text_names_hermes(
            "/opt/hermes-agent/venv/bin/python"
        ) is True

    def test_invalid_pid_inputs_do_not_crash(self):
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", True):
            assert _subprocess_compat.pid_is_hermes(-1) is False
            assert _subprocess_compat.pid_is_hermes(0) is False
            assert _subprocess_compat.pid_is_hermes("not-a-pid") is False
            assert _subprocess_compat.pid_is_hermes(True) is False

    def test_probe_matches_hermes_like_process(self):
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", True), mock.patch.object(
            _subprocess_compat, "_process_start_time", return_value=123
        ), mock.patch.object(
            _subprocess_compat, "_process_command_is_hermes", return_value=True
        ):
            assert _subprocess_compat.pid_is_hermes(1234) is True

    def test_probe_rejects_recycled_process_identity(self):
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", True), mock.patch.object(
            _subprocess_compat, "_process_start_time", return_value=456
        ), mock.patch.object(
            _subprocess_compat, "_process_command_is_hermes", return_value=True
        ):
            assert _subprocess_compat.pid_is_hermes(
                1234, expected_start_time=123
            ) is False

    def test_probe_rejects_foreign_process(self):
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", True), mock.patch.object(
            _subprocess_compat, "_process_start_time", return_value=123
        ), mock.patch.object(
            _subprocess_compat, "_process_command_is_hermes", return_value=False
        ):
            assert _subprocess_compat.pid_is_hermes(1234) is False

    def test_probe_blank_stdout_fails_closed(self):
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", True), mock.patch.object(
            _subprocess_compat, "_process_start_time", return_value=None
        ):
            assert _subprocess_compat.pid_is_hermes(1234) is False

    def test_probe_oserror_fails_closed(self):
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", True), mock.patch.object(
            _subprocess_compat, "_process_start_time", side_effect=OSError("broken pipe")
        ):
            assert _subprocess_compat.pid_is_hermes(1234) is False

    @pytest.mark.platforms("windows")  # real probe is windows-only
    def test_missing_pid_real_probe_fails_closed(self):
        # A PID that cannot exist must never be judged Hermes-owned.
        assert _subprocess_compat.pid_is_hermes(2**24) is False


class TestKillProcessTree:
    """kill_process_tree operates on our own retained Popen handle.

    A retained handle pins the PID (the child cannot be reaped while the
    handle is open), so PID recycling is impossible there and the identity
    guard deliberately does NOT apply — it could only false-refuse a
    legitimate cleanup. These tests pin that contract for the legacy
    Windows fallback path.
    """

    def _proc(self, pid=4321):
        return mock.Mock(pid=pid)

    def test_retained_handle_is_taskkilled_without_probe(self):
        with mock.patch.object(_subprocess_compat, "IS_WINDOWS", True), mock.patch.object(
            _subprocess_compat, "pid_is_hermes"
        ) as guard, mock.patch.object(_subprocess_compat.subprocess, "run") as run:
            _subprocess_compat._legacy_kill_process_tree(self._proc())
            guard.assert_not_called()
            run.assert_called_once()
            argv = run.call_args.args[0]
            assert argv[0] == "taskkill"
            assert "/PID" in argv
            assert str(4321) in argv


class TestHermesHomeForPid:
    """Tri-state owner resolution: a readable environment always names a home."""

    @pytest.mark.platforms("posix")  # POSIX default home is $HOME/.hermes
    def test_readable_env_without_var_resolves_to_that_process_default_home(self, monkeypatch, tmp_path):
        """The common install shape exports no HERMES_HOME: the backend lives in its user's
        platform default home, and a default-home ``--stop`` must still find it (#113978)."""
        home = str(tmp_path / "alice")
        monkeypatch.setattr(process_inventory, "_pid_environ", lambda pid: {"HOME": home})
        monkeypatch.setattr(process_inventory, "_process_cmdline_for_pid",
                            lambda pid: ["hermes", "--profile", "work", "serve"] if pid == 2 else ["hermes", "serve"])

        assert process_inventory._hermes_home_for_pid(1) == f"{home}/.hermes"
        # ``-p``/``--profile`` is applied to os.environ after exec, invisible in /proc environ.
        assert process_inventory._hermes_home_for_pid(2) == f"{home}/.hermes/profiles/work"

    # REGRESSION (#116906): a systemd/launchd unit with a scrubbed environment exports no HOME.
    # The target resolves its own default home from the password database, so attributing it to
    # the INSPECTING process's home named another user's directory — and `hermes update` /
    # `--stop` then acted on the wrong profile root.
    def _posix_scrubbed_unit(self, monkeypatch, tmp_path, passwd_home):
        """A unit whose environment carries neither HOME nor HERMES_HOME, on the POSIX branch."""
        monkeypatch.setattr(process_inventory.sys, "platform", "linux")
        monkeypatch.setattr(process_inventory, "_pid_environ", lambda pid: {})
        monkeypatch.setattr(process_inventory, "_pid_passwd_home", lambda pid: passwd_home)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "inspecting-user"))
        monkeypatch.setattr(process_inventory, "_process_cmdline_for_pid", lambda pid: ["hermes", "serve"])

    def test_scrubbed_unit_env_resolves_to_the_owners_passwd_home(self, monkeypatch, tmp_path):
        service_home = tmp_path / "hermes-service"
        self._posix_scrubbed_unit(monkeypatch, tmp_path, str(service_home))

        assert Path(process_inventory._hermes_home_for_pid(1)) == service_home / ".hermes"

    def test_unreadable_passwd_entry_keeps_the_existing_fallback(self, monkeypatch, tmp_path):
        """No owner, no entry: the previous behaviour stands rather than resolving to nothing."""
        self._posix_scrubbed_unit(monkeypatch, tmp_path, None)

        assert Path(process_inventory._hermes_home_for_pid(1)) == tmp_path / "inspecting-user" / ".hermes"

    def test_root_shaped_hermes_home_follows_the_flag_and_the_sticky_active_profile(self, monkeypatch, tmp_path):
        """Mirror ``_apply_profile_override``: an exported root ``HERMES_HOME`` is the root, not the
        home — ``-p work`` and ``hermes profile use work`` both land in ``<root>/profiles/work``."""
        root = tmp_path / ".hermes"
        root.mkdir()
        monkeypatch.setattr(process_inventory, "_pid_environ",
                            lambda pid: {"HOME": str(tmp_path), "HERMES_HOME": str(root)})
        monkeypatch.setattr(process_inventory, "_process_cmdline_for_pid",
                            lambda pid: ["hermes", "-p", "work", "serve"] if pid == 2 else ["hermes", "serve"])

        assert process_inventory._hermes_home_for_pid(2) == str(root / "profiles" / "work")
        assert process_inventory._hermes_home_for_pid(1) == str(root)  # no flag, no active_profile
        (root / "active_profile").write_text("work", encoding="utf-8")
        assert process_inventory._hermes_home_for_pid(1) == str(root / "profiles" / "work")
        # A profile-shaped HERMES_HOME without a flag is the home itself (root = its grandparent).
        monkeypatch.setattr(process_inventory, "_pid_environ",
                            lambda pid: {"HERMES_HOME": str(root / "profiles" / "ops")})
        assert process_inventory._hermes_home_for_pid(1) == str(root / "profiles" / "ops")

    def test_unreadable_env_is_none_and_spared(self, monkeypatch):
        monkeypatch.setattr(process_inventory, "_pid_environ", lambda pid: None)
        assert process_inventory._hermes_home_for_pid(7) is None
