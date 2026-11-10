"""Frozen updater surface for the retired web-UI build helpers.

``hermes update`` replaces the checkout underneath a RUNNING process; code shipped before the
dashboard removal imports these names from the NEW tree after the swap. The live build is now
TUI-only (``hermes_cli/source_build.py``), so the retired entrypoints stop for relaunch instead of
building a product that no longer exists (``tests/compat/README.md``: restore the name, a stub is
fine). ``_BYTECODE_FINGERPRINT_FILE`` stays data only — the live sweep is
``hermes_cli/update_bytecode.py``.
"""
from pathlib import Path
from typing import NoReturn

from hermes_cli._old_updater import stop_for_relaunch

_BYTECODE_FINGERPRINT_FILE = ".bytecode-fingerprint"


def _run_with_idle_timeout(
    command: list[str], cwd: Path, *, timeout: float = 900, **_kwargs,
) -> NoReturn:
    # Shim to stop the old updater doing work until relaunch, not run a build.
    stop_for_relaunch()


def _run_npm_install_deterministic(command: str, project_dir: Path, **_kwargs) -> NoReturn:
    # Shim to stop the old updater doing work until relaunch, not install node deps.
    stop_for_relaunch()


def _nixos_build_env() -> NoReturn:
    # Shim to stop the old updater doing work until relaunch, not select a Nix environment.
    stop_for_relaunch()


def _web_ui_build_needed(web_dir: Path) -> NoReturn:
    # Shim to stop the old updater doing work until relaunch, not select a build.
    stop_for_relaunch()


def _do_build_web_ui(web_dir: Path, *, fatal: bool = False) -> NoReturn:
    # Shim to stop the old updater doing work until relaunch, not build a web UI.
    stop_for_relaunch()
