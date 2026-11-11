"""An old `hermes update` must still find every name it loads mid-swap.

`hermes update` replaces the checkout underneath a RUNNING process. The
old process then lazy-imports from the new tree: whatever it asks for
must still exist, or the user's update dies half-applied. The names it
can ask for are the contract of updaters shipped BEFORE the PM migration:
EVERY commit reachable from an explicit pre-PM cutoff, back to the first
cmd_update. The checked-in tests/compat/old_updater_surface.json already
contains a history-plus-tree superset; keep enforcing those names, but do
not continually expand it with new PM updater imports. Moving the
implementation to pm does not retire already-running old updaters.
Historical entrypoints, extractions, renamed and deleted helpers remain
part of the contract.

Regeneration requires a full clone. These tests deliberately consume the
checked-in names and resolve them against the current tree, so shallow CI can
enforce the contract without reconstructing (or silently truncating) it.

`managed_uv._reload_hermes_constants` is the scar proving the failure
mode is real: a live updater hit ``cannot import name 'venv_python_path'
from 'hermes_constants'`` while the NEW file on disk plainly held it.

If this test fails you have two honest options:
* restore the name (a stub with the old signature is fine), or
* prove no updater in the pre-PM history loads it, then review a full
  history audit at the same cutoff (the existing JSON records it under
  stats.history.history_ref):
      python scripts/audit-old-updater-imports.py --ref PRE_PM_COMMIT --freeze \
          tests/compat/old_updater_surface.json
New updater imports are not grounds for regeneration or for advancing the
cutoff to a later origin/main. Hand-trimming the JSON is how someone's
install bricks mid-update.

The test resolves names statically (AST over the files) rather than
importing. The removal plan's D9 exception explicitly retires old web-build
and dashboard/serve updater handoffs; those exact names are excluded below
while the remaining frozen history stays enforced.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SURFACE_FILE = REPO_ROOT / "tests" / "compat" / "old_updater_surface.json"

# One authority for resolution: the audit script itself. The test must
# agree with --check byte-for-byte or the two drift apart.
import importlib.util as _ilu
import sys as _sys

_spec = _ilu.spec_from_file_location(
    "audit_old_updater_imports",
    REPO_ROOT / "scripts" / "audit-old-updater-imports.py",
)
assert _spec is not None and _spec.loader is not None
_audit = _ilu.module_from_spec(_spec)
# dataclass decorators resolve their defining module through sys.modules
# at class-creation time; exec without registration dies on it.
_sys.modules["audit_old_updater_imports"] = _audit
_spec.loader.exec_module(_audit)


def _load_surface() -> dict:
    return json.loads(SURFACE_FILE.read_text())


_RETIRED_BY_D9 = {
    "hermes_cli.main::ShimQuarantineError",
    "hermes_cli.main::_BYTECODE_FINGERPRINT_FILE",
    "hermes_cli.main::_desktop_stamp_path",
    "hermes_cli.main::_detect_broken_lazy_refresh_imports",
    "hermes_cli.main::_expected_windows_pe_machines",
    "hermes_cli.main::_hermes_exe_shims",
    "hermes_cli.main::_insert_python_pin",
    "hermes_cli.main::_interpreter_scripts_dir",
    "hermes_cli.main::_load_installable_optional_extras",
    "hermes_cli.main::_parse_pe_machine",
    "hermes_cli.main::_quarantine_running_hermes_exe",
    "hermes_cli.main::_repair_broken_lazy_refresh_imports",
    "hermes_cli.main::_resolve_install_target_python",
    "hermes_cli.main::_restore_quarantined_exes",
    "hermes_cli.main::_run_install_with_heartbeat",
    "hermes_cli.main::_run_npm_install_deterministic",
    "hermes_cli.main::_run_package_only_install",
    "hermes_cli.main::_run_quarantined_install",
    "hermes_cli.main::_run_with_idle_timeout",
    "hermes_cli.main::_self",
    "hermes_cli.main::_verify_console_scripts_installed",
    "hermes_cli.main::_verify_core_dependencies_installed",
    "hermes_cli.main::_web_ui_build_needed",
    "hermes_cli.main::_windows_native_machine",
    "hermes_cli.main::_windows_shim_in_process_chain",
    "hermes_cli.main::_write_web_ui_build_stamp",
    "hermes_cli.update_cmd::_finish_dashboard_update_cleanup",
    "hermes_cli.update_cmd_maint::_refresh_dashboard_after_update",
}


def _pairs(entries: list[str]) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    for entry in entries:
        if entry in _RETIRED_BY_D9:
            continue
        module, _, symbol = entry.partition("::")
        out.append((module, symbol or None))
    return out


class TestTheFrozenSurfaceStillResolves:
    """Every bare name in the retained frozen superset must exist in THIS tree."""

    @pytest.mark.parametrize(
        "module,symbol",
        _pairs(_load_surface()["bare"]),
        ids=lambda v: v or "<module>",
    )
    def test_bare_name_exists(self, module: str, symbol: str | None):
        ok, why = _audit.resolve_in_tree(module, symbol, REPO_ROOT)
        assert ok, (
            f"{why} — but the retained old-updater surface requires it AFTER "
            f"the checkout swap. Restore the name (a compat stub is fine) or "
            f"regenerate the frozen surface on a full clone; see this "
            f"file's docstring."
        )


class TestTheFrozenFileIsSane:
    """Catch a corrupted or hand-trimmed freeze before it lies to us."""

    def test_d9_retirement_is_limited_to_the_old_web_build_shims(self):
        assert _RETIRED_BY_D9 <= set(_load_surface()["bare"])

    def test_has_historical_load_bearing_names(self):
        # Spot-check names loaded by pre-PM updaters. If any of
        # these fall out of the frozen file, the freeze itself went wrong
        # (shallow clone, wrong branch) — the resolver test above would
        # pass vacuously.
        bare = set(_load_surface()["bare"])
        for anchor in (
            "hermes_constants::with_hermes_node_path",
            "hermes_constants::venv_python_path",
            "hermes_cli.gitlock::clear_stale_git_locks",
            "hermes_cli.managed_uv::ensure_uv",
            "hermes_cli.managed_uv::rebuild_venv",
            "hermes_cli._subprocess_compat::run",
            # Loaded by v0.21.6+ updaters after the swap: the parent restarting paused gateways.
            "tools.environments.local::served_profile_child_env",
            "gateway.status::live_gateway_pid_for_home",
            "hermes_cli.gateway_windows::_spawn_detached",
            "hermes_cli.update_fleet_scope::gateway_pid_home",
        ):
            assert anchor in bare, (
                f"{anchor} missing from the frozen surface — the freeze "
                f"went wrong (wrong branch, or the audit lost its "
                f"entrypoints); regenerate and eyeball the diff."
            )

    def test_frozen_history_is_complete_including_the_retained_union(self):
        frozen = _load_surface()
        stats = frozen["stats"]
        assert stats.get("mode") in {"history", "union"}, (
            "frozen surface must include the complete pre-PM history; "
            "a current-tree-only audit cannot establish that contract."
        )
        # The existing union remains a safe superset, not a requirement to
        # add today's updater imports or regenerate its tree half.
        history = stats["history"] if stats["mode"] == "union" else stats
        assert history.get("complete_history") is True
        assert history["commits"] > 0
        assert history["roots"] and history["entrypoint_paths"]
        assert "hermes_cli/main.py" in history["entrypoint_paths"], (
            "the freeze omitted the original inline cmd_update history"
        )
        assert history["history_ref"]
        analyzed = set(history["files_analyzed"])
        for must_see in ("hermes_cli/update_cmd.py", "hermes_cli/managed_uv.py"):
            assert must_see in analyzed, (
                f"{must_see} was not analyzed for the freeze — the audit "
                f"lost part of the update flow; a vacuously small surface "
                f"cannot guard anything."
            )

        assert not set(frozen["bare"]) & set(frozen["guarded_only"])
