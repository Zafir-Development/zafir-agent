"""expose_cli — the launcher owner repairs PATH conveniences.

The installers write ~/.local/bin/hermes* once, at install time. This
step rewrites them when they drift (moved checkout, recreated venv,
deleted by hand) and — just as load-bearing — REFUSES to touch a
launcher that belongs to a different install sharing the link dir.
Real files under a temp HOME; no mocks of the things being tested.

The wrapper-writing surface is POSIX-only by design (Windows exposure is
installer-owned), so the behaviour tests skip on win32 and the win32
gate gets its own test.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from hermes_cli import _launchers, post_update

posix_only = pytest.mark.platforms("posix")


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    """A venv-shaped install root plus an isolated HOME."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv("HERMES_HOME", str(home))

    root = tmp_path / "checkout"
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "python").write_text("#!fake\n", encoding="utf-8")
    (root / "hermes").write_text("# entrypoint\n", encoding="utf-8")
    (root / "run_agent.py").write_text("# agent\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_INSTALL_ROOT", str(root))
    store = tmp_path / "tools"
    store.mkdir()
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(store))
    interpreter = Path(sys._base_executable).resolve()
    (store / "facts.json").write_text(json.dumps({"schema": 1, "packages": {"python": {
        "entry": str(interpreter.parent if os.name == "nt" else interpreter.parents[1]),
    }}}), encoding="utf-8")
    return home, root


@pytest.mark.platforms("windows")
@pytest.mark.parametrize("create", [True, False])
def test_windows_converges_on_the_installer_user_bin(create, monkeypatch, tmp_path):
    """Windows converges on the installer's convention ($HERMES_HOME\\bin + User PATH); an update
    no longer skips as "installer-owned" and leaves a venv\\Scripts machine behind."""
    calls = []
    monkeypatch.setattr(_launchers, "_expose_windows_user_bin",
                        lambda root, *, create: calls.append(create) or {"ok": True, "written": []})
    monkeypatch.setenv("HERMES_INSTALL_ROOT", str(tmp_path))
    assert _launchers.expose_cli(create=create) == {"ok": True, "written": []}
    assert calls == [create]


@pytest.fixture
def user_path_writes(monkeypatch):
    """User PATH registrations, recorded instead of written to the registry.

    Launcher publication is stubbed: these tests cover only the registration
    decision, and publication has its own tests."""
    registered = []
    monkeypatch.setattr(_launchers, "ensure_install_launchers",
                        lambda root, out: [str(out / f"{name}.exe") for name in _launchers.WINDOWS_BIN_LAUNCHERS])
    monkeypatch.setattr(_launchers, "_register_windows_user_path",
                        lambda entry: registered.append(Path(entry)) or "added")
    return registered


@pytest.mark.platforms("windows")
def test_sandbox_home_keeps_its_launchers_off_the_user_path(user_path_writes, tmp_path, monkeypatch):
    """A review sandbox's HERMES_HOME publishes into its own bin and never reaches the User PATH.

    The console environment is not stubbed: Windows builds it from the user's
    stored variables, so these overrides are exactly what a sandbox sets."""
    box = tmp_path / "box"
    monkeypatch.setenv("HERMES_HOME", str(box / "hermes"))
    monkeypatch.setenv("LOCALAPPDATA", str(box / "local"))
    monkeypatch.setenv("USERPROFILE", str(box / "user"))

    result = _launchers._expose_windows_user_bin(tmp_path / "checkout", create=True)

    assert result["ok"] and result["skipped"]
    assert result["written"] == [f"{name}.exe" for name in _launchers.WINDOWS_BIN_LAUNCHERS]
    assert user_path_writes == []


@pytest.mark.platforms("windows")
@pytest.mark.parametrize("hermes_home", [None, ("hermes",), ("hermes", "profiles", "work")])
def test_the_home_new_consoles_use_registers_its_bin(user_path_writes, hermes_home, tmp_path, monkeypatch):
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    if hermes_home is None:
        monkeypatch.delenv("HERMES_HOME", raising=False)
    else:
        monkeypatch.setenv("HERMES_HOME", str(local.joinpath(*hermes_home)))
    monkeypatch.setattr(_launchers, "_new_console_environment", lambda: {"LOCALAPPDATA": str(local)})

    result = _launchers._expose_windows_user_bin(tmp_path / "checkout", create=True)

    assert result["path"] == "added"
    assert user_path_writes == [local / "hermes" / "bin"]


@pytest.mark.platforms("windows")
@pytest.mark.parametrize("stored_home, override", [
    ("%LOCALAPPDATA%\\hermes-data", "LOCALAPPDATA"),
    ("~\\hermes-data", "USERPROFILE"),
])
def test_inherited_home_reference_expands_from_the_console_environment(
        user_path_writes, stored_home, override, tmp_path, monkeypatch):
    """A sandbox that inherits a stored HERMES_HOME such as %LOCALAPPDATA%\\x and overrides
    LOCALAPPDATA resolves a different root from a new console, so it must not match."""
    real = tmp_path / "real"
    console = {"LOCALAPPDATA": str(real / "local"), "USERPROFILE": str(real / "user"), "HERMES_HOME": stored_home}
    monkeypatch.setattr(_launchers, "_new_console_environment", lambda: dict(console))
    monkeypatch.setenv("LOCALAPPDATA", console["LOCALAPPDATA"])
    monkeypatch.setenv("USERPROFILE", console["USERPROFILE"])
    monkeypatch.setenv("HERMES_HOME", stored_home)
    monkeypatch.setenv(override, str(tmp_path / "box" / override.lower()))

    result = _launchers._expose_windows_user_bin(tmp_path / "checkout", create=True)

    assert result["skipped"]
    assert user_path_writes == []


@pytest.mark.platforms("windows")
def test_unknown_console_environment_leaves_the_user_path(user_path_writes, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setattr(_launchers, "_new_console_environment", lambda: None)

    assert _launchers._expose_windows_user_bin(tmp_path / "checkout", create=True)["skipped"]
    assert user_path_writes == []


@pytest.mark.platforms("windows")
def test_new_console_environment_ignores_this_process(tmp_path, monkeypatch):
    """The real Win32 read: variables set only in this process are absent from a new console's environment."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HERMES_TEST_ONLY_IN_THIS_PROCESS", "1")

    environ = _launchers._new_console_environment()

    assert environ is not None
    assert "HERMES_TEST_ONLY_IN_THIS_PROCESS" not in environ
    assert environ.get("LOCALAPPDATA")
    assert Path(environ["LOCALAPPDATA"]) != tmp_path / "local"
    assert environ.get("HERMES_HOME") != str(tmp_path / "hermes")


@pytest.mark.platforms("windows")
def test_environment_block_reader_counts_utf16_units():
    """An emoji takes two UTF-16 units but one Python character; the variables after it must survive."""
    import ctypes

    block = ctypes.create_unicode_buffer("A=1\0MOOD=\U0001F600\0HERMES_HOME=C:\\h\0=C:=C:\\\0\0")

    assert _launchers._read_environment_block(ctypes.addressof(block)) == {
        "A": "1", "MOOD": "\U0001F600", "HERMES_HOME": "C:\\h"}


def _windows_home(tmp_path, monkeypatch) -> Path:
    """The default data root under a temp LOCALAPPDATA, with a store interpreter; new consoles use it.

    distlib is switched off, so publication writes the ``.cmd`` form on every test host."""
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("HERMES_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(_launchers, "_new_console_environment", lambda: {"LOCALAPPDATA": str(local)})
    monkeypatch.setattr(_launchers, "_load_script_maker", lambda: None)
    monkeypatch.setattr(_launchers, "_store_script_maker", lambda python_exe: None)
    home = local / "hermes"
    _store_python(home).parent.mkdir(parents=True)
    _store_python(home).touch()
    (home / "tools" / "facts.json").write_text(
        json.dumps({"schema": 1, "packages": {"python": {"entry": _store_python(home).parent.name}}}),
        encoding="utf-8")
    return home


def _store_python(home: Path) -> Path:
    return home / "tools" / "python-fixture" / "python.exe"


def _checkout(path: Path) -> Path:
    (path / ".git").mkdir(parents=True)
    (path / "install-stamp.json").write_text(json.dumps({"updateMechanism": "self"}), encoding="utf-8")
    return path.resolve()


def _write_exe_launcher(target: Path, python: Path, root: Path) -> None:
    """distlib's shape: loader stub, '#!<python> -I' shebang, then a zip holding the launcher script."""
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("__main__.py", _launchers._launcher_script(target.stem, root, None))
    target.write_bytes(b"MZ" + b"\x00" * 64 + b"#!" + str(python).encode() + b" -I\r\n" + payload.getvalue())


def _command(home: Path) -> Path:
    """The ``hermes`` a console runs: PATHEXT resolves .exe before .cmd."""
    exe = home / "bin" / "hermes.exe"
    return exe if exe.exists() else home / "bin" / "hermes.cmd"


@pytest.fixture
def path_registrations(monkeypatch):
    registered = []
    monkeypatch.setattr(_launchers, "_register_windows_user_path",
                        lambda entry: registered.append(Path(entry)) or "added")
    return registered


@pytest.mark.platforms("windows")
@pytest.mark.parametrize("form", ["exe", "cmd"])
def test_review_tree_leaves_the_installed_commands_alone(form, path_registrations, tmp_path, monkeypatch):
    """A review tree started against the real home keeps the installed checkout's commands in its bin.

    Its boot bootstrap runs expose_cli too; republishing there would point every
    console's ``hermes`` at the review tree."""
    home = _windows_home(tmp_path, monkeypatch)
    installed = _checkout(home / "hermes-agent")
    review = _checkout(home / "reviews" / "pr-1" / "rebuild-wt")
    if form == "exe":
        (home / "bin").mkdir()
        for name in _launchers.WINDOWS_BIN_LAUNCHERS:
            _write_exe_launcher(home / "bin" / f"{name}.exe", _store_python(home), installed)
    else:
        assert _launchers._expose_windows_user_bin(installed, create=True)["path"] == "added"
    before = {path.name: path.read_bytes() for path in (home / "bin").iterdir()}

    result = _launchers._expose_windows_user_bin(review, create=True)

    assert {path.name: path.read_bytes() for path in (home / "bin").iterdir()} == before
    assert result == {"ok": True, "skipped": f"{home / 'bin' / f'hermes.{form}'} starts another checkout"}
    assert _launchers._launcher_checkout(_command(home)) == installed
    assert path_registrations == ([] if form == "exe" else [home / "bin"])


@pytest.mark.platforms("windows")
def test_review_tree_publishes_where_no_working_command_exists(path_registrations, tmp_path, monkeypatch):
    home = _windows_home(tmp_path, monkeypatch)
    first = _checkout(home / "reviews" / "pr-1" / "rebuild-wt")
    second = _checkout(home / "reviews" / "pr-2" / "rebuild-wt")

    assert "skipped" not in _launchers._expose_windows_user_bin(first, create=True)
    assert _launchers._launcher_checkout(_command(home)) == first

    # A command whose checkout is gone starts nothing, so it is replaced.
    shutil.rmtree(first)
    assert "skipped" not in _launchers._expose_windows_user_bin(second, create=True)
    assert _launchers._launcher_checkout(_command(home)) == second


@pytest.mark.platforms("windows")
def test_installed_checkout_takes_its_commands_back(path_registrations, tmp_path, monkeypatch):
    home = _windows_home(tmp_path, monkeypatch)
    installed = _checkout(home / "hermes-agent")
    review = _checkout(home / "reviews" / "pr-1" / "rebuild-wt")
    _launchers._expose_windows_user_bin(review, create=True)
    assert _launchers._launcher_checkout(_command(home)) == review

    assert "skipped" not in _launchers._expose_windows_user_bin(installed, create=True)
    assert _launchers._launcher_checkout(_command(home)) == installed


def test_registered_as_a_home_step():
    assert ("expose_cli", _launchers.expose_cli) in post_update.HOME_STEPS


class TestExposeCli:
    @posix_only
    @pytest.mark.parametrize("hermes", ["missing", "foreign"])
    def test_repair_only_preserves_missing_and_foreign_commands(self, fake_install, monkeypatch, hermes):
        home, root = fake_install
        monkeypatch.setattr("hermes_cli.config.load_config", lambda: pytest.fail("repair read config"))
        wrapper_dir = home / ".local" / "bin"
        extra = home / "bin"
        assert _launchers.expose_cli(create=False) == {"ok": True, "written": []}
        assert not wrapper_dir.exists()
        assert not extra.exists()
        assert {p.name for p in (root / ".hermes/bin").iterdir()} == set(_launchers.ENTRY_POINTS)

        # An owned ACP entry must be repaired even without an owned hermes
        # sibling admitting this directory. Its old target is already gone.
        extra.mkdir()
        dangling = root / "venv/bin/hermes-acp"
        acp = extra / "hermes-acp"
        acp.symlink_to(dangling)
        assert not acp.exists() and acp.is_symlink()
        foreign = b"#!/bin/sh\n# user-owned caf\xc3\xa9 command\nexit 19\n"
        if hermes == "foreign":
            (extra / "hermes").write_bytes(foreign)
        wrapper_dir.mkdir(parents=True)
        (wrapper_dir / "hermes").write_bytes(foreign)
        foreign_link = wrapper_dir / "hermes-acp"
        foreign_target = home / "other-install/hermes-acp"
        foreign_link.symlink_to(foreign_target)
        before = {path: path.lstat().st_mtime_ns for path in (wrapper_dir, wrapper_dir / "hermes", foreign_link)}

        assert _launchers.expose_cli(create=False) == {"ok": True, "written": ["hermes-acp"]}
        assert acp.is_file() and not acp.is_symlink() and os.access(acp, os.X_OK)
        assert not dangling.exists()
        assert not (extra / "hermes-agent").exists()
        assert not (wrapper_dir / "hermes-agent").exists()
        if hermes == "foreign":
            assert (extra / "hermes").read_bytes() == foreign
        else:
            assert not (extra / "hermes").exists()
        assert (wrapper_dir / "hermes").read_bytes() == foreign
        assert foreign_link.is_symlink() and foreign_link.readlink() == foreign_target
        assert before == {path: path.lstat().st_mtime_ns for path in before}
        assert _launchers.expose_cli(create=False) == {"ok": True, "written": []}

    @posix_only
    def test_writes_all_three_wrappers_fresh(self, fake_install):
        home, root = fake_install
        result = _launchers.expose_cli()
        assert result["ok"] is True
        assert sorted(result["written"]) == ["hermes", "hermes-acp", "hermes-agent"]
        for name in ("hermes", "hermes-agent", "hermes-acp"):
            wrapper = home / ".local" / "bin" / name
            body = wrapper.read_text(encoding="utf-8-sig")
            assert str(root) in body
            assert str(root / ".hermes" / "bin") in body
            assert os.access(wrapper, os.X_OK)



    @posix_only
    def test_leaves_another_installs_wrapper_alone(self, fake_install):
        home, _root = fake_install
        other = "/somewhere/else/checkout"
        wrapper_dir = home / ".local" / "bin"
        wrapper_dir.mkdir(parents=True)
        foreign = f'#!/bin/sh\nexec "{other}/venv/bin/python" "{other}/hermes" "$@"\n'
        (wrapper_dir / "hermes").write_text(foreign, encoding="utf-8")
        result = _launchers.expose_cli()
        assert (wrapper_dir / "hermes").read_text(encoding="utf-8-sig") == foreign
        assert "hermes" not in result["written"]
        # The other two had no file at all — those ARE written.
        assert sorted(result["written"]) == ["hermes-acp", "hermes-agent"]

    @posix_only
    def test_config_gate_disables(self, fake_install, monkeypatch):
        monkeypatch.setattr(
            "hermes_cli.config.load_config",
            lambda: {"cli": {"expose_on_path": False}},
        )
        result = _launchers.expose_cli()
        assert result == {"ok": True, "skipped": "config-disabled"}

    @posix_only
    def test_sealed_tree_without_venv_skips(self, fake_install, monkeypatch, tmp_path):
        (tmp_path / "tools" / "facts.json").unlink()
        bare = tmp_path / "sealed"
        bare.mkdir()
        monkeypatch.setenv("HERMES_INSTALL_ROOT", str(bare))
        result = _launchers.expose_cli()
        assert result == {"ok": True, "skipped": "no-store-python"}

    @posix_only
    def test_replaces_a_dangling_symlink_from_old_installs(self, fake_install):
        """#21454: `cat >` used to follow an old symlink into the venv and
        clobber the console script. The step must unlink FIRST."""
        home, root = fake_install
        wrapper_dir = home / ".local" / "bin"
        wrapper_dir.mkdir(parents=True)
        console_script = root / "venv" / "bin" / "hermes"
        console_script.write_text("# real console script\n", encoding="utf-8")
        (wrapper_dir / "hermes").symlink_to(console_script)
        result = _launchers.expose_cli()
        assert "hermes" in result["written"]
        # The venv console script survives untouched…
        assert console_script.read_text(encoding="utf-8-sig") == "# real console script\n"
        # …and the link-dir entry is now a real file, not a symlink.
        assert not (wrapper_dir / "hermes").is_symlink()
