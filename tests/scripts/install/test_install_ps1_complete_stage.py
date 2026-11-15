"""Stage-Complete must keep writing the bootstrap receipt and the chosen channel.

The GUI-installer removal dropped ``Stage-Complete`` from install.ps1 while
``Invoke-StageByName`` kept dispatching ``complete`` to it, so the final stage
died with ``Stage-Complete is not recognized`` (or, through ``-Stage complete
-Json``, an ``ok: false`` frame). The receipt is not cosmetic: its presence
marks the checkout a script install and ``hermes update`` refreshes it
(``hermes_cli/source_stamp.py``).

Dot-sourced probe: the stage's own work is the receipt write plus the
``hermes update --set-channel`` call, so ``Invoke-InstalledHermes`` is replaced
with a recorder and ``-Commit`` is passed to keep pinned-Git resolution out of
the path (the staged-git test drives that real path).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.platforms("windows")

INSTALLER = Path(__file__).resolve().parents[3] / "scripts" / "install.ps1"
COMMIT = "0123456789abcdef0123456789abcdef01234567"

PROBE = """
$ErrorActionPreference = "Stop"
. "@INSTALLER@"
$InstallDir = "@INSTALL_DIR@"
$Commit = "@COMMIT@"
$Branch = "main"
$Channel = "stable"
function Invoke-InstalledHermes { param([string[]]$CommandArgs) $script:hermesArgs = @($CommandArgs) }
Stage-Complete
$receipt = Get-Content -LiteralPath (Join-Path $InstallDir ".hermes-bootstrap-complete") -Raw | ConvertFrom-Json
[ordered]@{ receipt = $receipt; args = @($script:hermesArgs) } | ConvertTo-Json -Depth 5 -Compress
"""


def test_complete_stage_writes_receipt_and_preserves_chosen_channel(tmp_path):
    powershell = shutil.which("powershell")
    assert powershell, "Windows PowerShell 5.1 is part of every supported Windows"
    install_dir = tmp_path / "hermes-agent"
    install_dir.mkdir()
    script = (PROBE.replace("@INSTALLER@", str(INSTALLER))
                  .replace("@INSTALL_DIR@", str(install_dir))
                  .replace("@COMMIT@", COMMIT))
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])

    receipt = report["receipt"]
    assert set(receipt) == {"schemaVersion", "pinnedCommit", "pinnedBranch", "completedAt"}
    assert receipt["schemaVersion"] == 1
    assert receipt["pinnedCommit"] == COMMIT
    assert receipt["pinnedBranch"] == "main"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", receipt["completedAt"])
    assert report["args"] == ["update", "--set-channel", "stable"]
