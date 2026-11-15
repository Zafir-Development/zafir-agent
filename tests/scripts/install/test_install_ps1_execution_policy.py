"""The iex'd installer must reach the published launcher under Restricted policy.

`iex (irm .../install.ps1)` is a string, so execution policy never checks it.
Loading a helper .ps1 from disk is a file load, which the default Restricted
policy (Windows Sandbox, fresh machines) refuses: "cannot be loaded because
running scripts is disabled on this system". The installer therefore runs
`.hermes\\bin\\hermes.exe` (fallback `.hermes\\bin\\hermes.cmd`) directly --
an executable or a batch file, neither of which execution policy gates -- and
keeps the native exit-code contract (`setup` -> setup_failed, `gateway` ->
gateway_failed).
"""
from pathlib import Path
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.platforms("windows")
INSTALLER = Path(__file__).resolve().parents[3] / "scripts" / "install.ps1"


def _run_installer(powershell: str, install_root: Path, *arguments: str, cwd: Path) -> subprocess.CompletedProcess:
    """Dot-source the definitions, drop to Restricted, then run one stage step."""
    quoted_installer = str(INSTALLER).replace("'", "''")
    quoted_root = str(install_root).replace("'", "''")
    quoted_args = ", ".join(f"'{argument}'" for argument in arguments)
    command = (
        f". '{quoted_installer}'; "
        "Set-ExecutionPolicy -Scope Process Restricted -Force; "
        f"$InstallDir = '{quoted_root}'; "
        f"Invoke-InstalledHermes @({quoted_args})"
    )
    return subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False,
    )


def _write_launcher(install_root: Path, body: str) -> Path:
    launcher = install_root / ".hermes" / "bin" / "hermes.cmd"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(body.replace("\n", "\r\n"), encoding="utf-8")
    return launcher


def test_installed_hermes_runs_under_restricted_policy(tmp_path):
    powershell = shutil.which("powershell")
    assert powershell
    install_root = tmp_path / "install"
    _write_launcher(install_root, "@echo off\necho runtime-from %*\n")

    result = _run_installer(powershell, install_root, "setup", cwd=tmp_path)

    output = result.stdout + result.stderr
    assert "running scripts is disabled" not in output, output
    assert result.returncode == 0, output
    assert "runtime-from setup" in result.stdout, output


def test_installer_runs_launcher_from_apostrophe_account_path(tmp_path):
    """A Windows account apostrophe must survive the installer's launcher path."""
    powershell = shutil.which("powershell")
    assert powershell
    install_root = tmp_path / "O'Brien" / "hermes-agent"
    _write_launcher(install_root, "@echo off\necho setup-runtime-ok %*\n")

    result = _run_installer(powershell, install_root, "setup", cwd=tmp_path)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "setup-runtime-ok setup" in result.stdout, output


def test_launcher_exit_code_keeps_the_stage_classification(tmp_path):
    powershell = shutil.which("powershell")
    assert powershell
    install_root = tmp_path / "install"
    _write_launcher(install_root, "@echo off\nexit /b 3\n")

    result = _run_installer(powershell, install_root, "gateway", cwd=tmp_path)

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "hermes gateway failed (exit 3)" in output, output
