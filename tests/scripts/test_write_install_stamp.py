"""The emitted stamp must preserve build identity and reach the runtime reader."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/write_install_stamp.py"
# Exactly what scripts/termux/build_deb.sh passes in commit mode.
_TERMUX_COMMIT_BUILD_ARGS = [
    "--source", "commit-build",
    "--base-version", "0.19.0", "--display-version", "0.19.0", "--distance", "0",
    "--distribution", "apt-termux", "--update-mechanism", "external",
]


def _termux_writer_env(**overrides):
    env = {**os.environ, "HERMES_DESKTOP_VARIANT": "runtime", "HERMES_PAYLOAD_TAG": ""}
    env.pop("HERMES_BUILD_COMMIT", None)
    env.update(overrides)
    return env


@pytest.mark.parametrize("variant,distribution,mechanism,payload,tag", [
    ("", None, "self", "bootstrap", None),
    ("bootstrap", "docker", "external", "bootstrap", None),
    ("bundled", "desktop-app", "electron-updater", "bundled", "v0.18.0"),
    ("bundled", "desktop-app", "app-installer", "bundled", "v0.18.0"),
    ("bundled", "desktop-app", "microsoft-store", "bundled", "v0.18.0"),
    ("bundled", "desktop-app", "external", "bundled", "v0.18.0"),
    ("light", "desktop-app", "electron-updater", "light", "v0.18.0"),
    ("runtime", "apt-termux", "external", "runtime", "v0.18.0"),
])
def test_cli_stamp_roundtrip(tmp_path, monkeypatch, variant, distribution, mechanism, payload, tag):
    out = tmp_path / "install-stamp.json"
    script = Path(__file__).resolve().parents[2] / "scripts/write_install_stamp.py"
    env = {**os.environ, "HERMES_DESKTOP_VARIANT": variant, "HERMES_PAYLOAD_TAG": "v0.18.0"}
    args = [sys.executable, str(script), "--output", str(out), "--commit", "d" * 40,
            "--source", "ci", "--base-version", "0.18.0", "--distance", "0",
            "--update-mechanism", mechanism]
    if distribution:
        args += ["--distribution", distribution]
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8-sig"))
    assert {key: data[key] for key in ("source", "distribution", "updateMechanism", "payload", "tag", "commit")} == {
        "source": "ci", "distribution": distribution, "updateMechanism": mechanism,
        "payload": payload, "tag": tag, "commit": "d" * 40}
    assert data["baseVersion"] == data["displayVersion"] == "0.18.0"
    from hermes_cli.version_info import _stamp_version_info
    from hermes_cli.venv_sync import _is_sealed
    monkeypatch.setenv("HERMES_INSTALL_ROOT", str(tmp_path))
    if payload == "light":
        with pytest.raises(RuntimeError, match="light"):
            _stamp_version_info()
    else:
        info = _stamp_version_info()
        assert info is not None and info.commit == "d" * 40
        assert _is_sealed(tmp_path)
        (tmp_path / ".git").mkdir()
        assert not _is_sealed(tmp_path), "a stamped source checkout is not sealed"


@pytest.mark.parametrize("arguments", [[], ["--update-mechanism", "carrier-pigeon"]])
def test_missing_or_invalid_mechanism_cannot_emit_stamp(tmp_path, arguments):
    from scripts.write_install_stamp import build_stamp

    out = tmp_path / "install-stamp.json"
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "scripts/write_install_stamp.py"),
         "--output", str(out), "--commit", "a" * 40, *arguments],
        capture_output=True, text=True, timeout=30,
        check=False,
    )
    assert result.returncode != 0 and "--update-mechanism" in result.stderr
    assert not out.exists()
    with pytest.raises(SystemExit, match="invalid --update-mechanism"):
        build_stamp(commit="a" * 40, update_mechanism=arguments[-1] if arguments else "")


@pytest.mark.parametrize("variant,tag,error", [
    ("bundled", "", "HERMES_PAYLOAD_TAG"), ("light", "", "HERMES_PAYLOAD_TAG"),
    ("chonky", "v0.18.0", "unknown HERMES_DESKTOP_VARIANT"),
])
def test_invalid_variant_cannot_emit_stamp(tmp_path, variant, tag, error):
    out = tmp_path / "install-stamp.json"
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "scripts/write_install_stamp.py"),
         "--output", str(out), "--commit", "d" * 40, "--base-version", "0.18.0",
         "--update-mechanism", "self"],
        env={**os.environ, "HERMES_DESKTOP_VARIANT": variant, "HERMES_PAYLOAD_TAG": tag},
        capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode != 0 and error in result.stderr
    assert not out.exists()


def test_tagless_runtime_commit_build_emits_commit_identity(tmp_path, monkeypatch):
    """build_deb.sh commit mode: runtime payload, empty tag, explicit full SHA."""
    from hermes_cli.version_info import _stamp_version_info

    commit = "c" * 40
    out = tmp_path / "app" / "install-stamp.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(out), "--commit", commit, *_TERMUX_COMMIT_BUILD_ARGS],
        env=_termux_writer_env(), capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8-sig"))
    assert {key: data[key] for key in ("payload", "tag", "source", "commit", "distribution", "updateMechanism")} == {
        "payload": "runtime", "tag": None, "source": "commit-build", "commit": commit,
        "distribution": "apt-termux", "updateMechanism": "external"}
    assert data["baseVersion"] == data["displayVersion"] == "0.19.0"

    # The updater refusal and the banner read this identity back out of the stamp.
    monkeypatch.setenv("HERMES_INSTALL_ROOT", str(out.parent))
    info = _stamp_version_info()
    assert info is not None
    assert (info.commit, info.source, info.base_version) == (commit, "commit-build", "0.19.0")


@pytest.mark.parametrize("identity", [
    [], ["--commit", "c" * 12], ["--commit", "g" * 40], ["--commit", "0" * 40],
], ids=["no-commit", "short-commit", "non-hex-commit", "fallback-commit"])
def test_tagless_runtime_refuses_without_explicit_full_commit(tmp_path, identity):
    """Only an explicitly admitted full SHA makes a tagless runtime stamp valid."""
    out = tmp_path / "install-stamp.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(out), *_TERMUX_COMMIT_BUILD_ARGS, *identity],
        env=_termux_writer_env(GITHUB_SHA="c" * 40),
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode != 0 and "HERMES_PAYLOAD_TAG" in result.stderr
    assert not out.exists()


def test_packaged_identity_never_falls_back_to_project_metadata(tmp_path, monkeypatch):
    from scripts import write_install_stamp
    from hermes_cli.version_info import _stamp_version_info

    (tmp_path / "hermes_cli").mkdir()
    (tmp_path / "hermes_cli" / "_version.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "8.8.8"\n', encoding="utf-8")
    monkeypatch.setattr(write_install_stamp, "_REPO_ROOT", tmp_path)
    monkeypatch.setenv("HERMES_INSTALL_ROOT", str(tmp_path))

    # No reachable release (a tagless docker build): the admitted commit is the whole identity.
    write_install_stamp.write_stamp(
        tmp_path / "install-stamp.json", update_mechanism="external", commit="d" * 40, source="ci", dirty=False,
    )
    info = _stamp_version_info()
    assert info is not None
    assert (info.base_version, info.derived_version, info.commit) == ("unknown", "git.ddddddd", "d" * 40)

    stamp = write_install_stamp.build_stamp(
        update_mechanism="external", commit="d" * 40, source="ci",
        base_version="1.2.3", distance=0,
    )

    assert stamp["baseVersion"] == stamp["displayVersion"] == "1.2.3"
