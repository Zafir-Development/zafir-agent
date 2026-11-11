"""Termux packaging refuses identity mistakes before modifying its payload."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
bash = shutil.which("bash")
pytestmark = pytest.mark.skipif(bash is None, reason="bash is required to run the packaging script")


def _native_tool(name: str) -> str:
    """Resolve *name* to an executable the child process can actually start."""
    candidates = [hit for hit in (shutil.which(name),) if hit]
    if sys.platform == "win32":
        git_base = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git"
        for rel in (("cmd", f"{name}.exe"), ("bin", f"{name}.exe"), ("usr", "bin", f"{name}.exe")):
            path = git_base.joinpath(*rel)
            if path.exists():
                candidates.append(str(path))
    for cand in candidates:
        if "windowsapps" not in cand.lower():
            return cand
    return candidates[0]


def _child_env(**overrides: str) -> dict:
    env = os.environ.copy()
    if sys.platform == "win32":
        env.setdefault("SystemRoot", r"C:\Windows")
        env.setdefault("ComSpec", r"C:\Windows\system32\cmd.exe")
        env.setdefault("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    env.update(overrides)
    return env


_GIT = _native_tool("git")
_BASH = _native_tool("bash")


def _git(*args: str, cwd: Path) -> str:
    out = subprocess.run(
        [_GIT, *args], cwd=cwd, capture_output=True, text=True, check=True,
        env=_child_env(),
    )
    return out.stdout.strip()


def _seed_repo(root: Path) -> tuple[Path, Path]:
    """origin (upstream) + clone (where releases are tagged from)."""
    origin = root / "origin"
    origin.mkdir()
    _git("init", "-b", "main", cwd=origin)
    _git("config", "user.email", "ci@example.com", cwd=origin)
    _git("config", "user.name", "ci", cwd=origin)
    (origin / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.1.2"\n', encoding="utf-8")
    (origin / "README.md").write_text("seed\n", encoding="utf-8")
    _git("add", "-A", cwd=origin)
    _git("commit", "-m", "seed", cwd=origin)

    clone = root / "clone"
    _git("clone", str(origin), str(clone), cwd=root)
    _git("config", "user.email", "ci@example.com", cwd=clone)
    _git("config", "user.name", "ci", cwd=clone)
    return origin, clone


def test_deb_identity_refusal_leaves_payload_and_output_untouched(tmp_path):
    _, repo = _seed_repo(tmp_path)
    commit = _git('rev-parse', 'HEAD', cwd=repo)
    payload = tmp_path / 'payload'
    (payload / 'app').mkdir(parents=True)
    (payload / 'app/pyproject.toml').write_bytes((repo / 'pyproject.toml').read_bytes())
    (payload / 'venv').mkdir()
    witness = payload / 'venv/keep'
    witness.write_bytes(b'prior dependency tree')
    out = tmp_path / 'output'
    helper = tmp_path / 'bin'
    helper.mkdir()
    boundary = tmp_path / 'native-boundary'
    for name in ('docker', 'dpkg-deb', 'jq'):
        tool = helper / name
        tool.write_text(
            f'#!/bin/sh\nprintf %s {shlex.quote(name)} > {shlex.quote(str(boundary))}\nexit 87\n',
            encoding='utf-8', newline='\n')
        tool.chmod(0o755)
    python = helper / 'python3'
    python.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n',
                      encoding='utf-8', newline='\n')
    python.chmod(0o755)
    env = _child_env(HERMES_PAYLOAD_TAG='', HERMES_BUILD_COMMIT='', GIT_ALLOW_PROTOCOL='file',
                     PYTHONUTF8='1')
    for name in ('MSYS_NO_PATHCONV', 'MSYS2_ARG_CONV_EXCL', 'GIT_DIR', 'GIT_WORK_TREE', 'PYTHONPATH', 'PYTHONHOME'):
        env.pop(name, None)
    env['PATH'] = os.pathsep.join([str(helper), str(Path(_GIT).parent), env.get('PATH', '')])
    args = ['--repo', str(repo), '--payload', str(payload), '--out', str(out)]

    def invoke(identity):
        result = subprocess.run([_BASH, str(ROOT / 'scripts/termux/build_deb.sh'), *args, *identity],
                                cwd=tmp_path, env=env, capture_output=True, text=True,
                                encoding='utf-8', timeout=30, check=False)
        assert result.returncode != 0, result.stdout + result.stderr
        assert not boundary.exists(), 'identity refusal reached the native builder'
        assert witness.read_bytes() == b'prior dependency tree'
        assert not out.exists(), result.stdout + result.stderr
        return result.stdout + result.stderr

    assert 'not the requested commit' in invoke(['--commit', 'a' * 40])
    assert 'exact full' in invoke(['--commit', 'short'])
    assert 'usage:' in invoke(['--tag', 'v0.1.2', '--commit', commit])
    # Python package metadata is an inert placeholder; commit admission comes
    # from the selected checkout and flows to install-stamp.json later.
    (payload / 'app/pyproject.toml').write_text('[project]\nversion="9.9.9"\n', encoding='utf-8')
    assert '--tui-product is required' in invoke(['--commit', commit])
