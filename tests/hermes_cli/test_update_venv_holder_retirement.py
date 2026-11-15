"""PM updates do not require the currently running venv to become unoccupied."""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from hermes_cli import main, update_cmd, update_cmd_windows


@pytest.mark.parametrize("gateway_mode", [False, True])
def test_gateway_ancestor_refusal_never_kills_unknown_ancestry(monkeypatch, gateway_mode):
    """The live guard only refuses a tree-kill when a nominated gateway is positively an ancestor."""
    from hermes_cli import gateway
    import psutil

    forbidden = Mock(side_effect=AssertionError("refusal probe performed work"))
    monkeypatch.setattr(gateway, "_is_pid_ancestor_of_current_process", lambda pid: False)
    monkeypatch.setattr(psutil, "Process", forbidden)
    monkeypatch.setattr(update_cmd_windows.subprocess, "run", forbidden)
    monkeypatch.setattr(os, "kill", forbidden)
    assert update_cmd._refuse_gateway_ancestor_tree_kill([123, 456], gateway_mode=gateway_mode) is False
    forbidden.assert_not_called()


def test_command_reaches_checkout_preparation_without_holder_gates(monkeypatch, tmp_path):
    from hermes_cli import update_inventory

    class ReachedCheckout(BaseException):
        pass

    reached = []
    forbidden = Mock(side_effect=AssertionError("current update called a retired holder gate"))
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(main, "_update_preflight_handled", lambda args: False)
    monkeypatch.setattr(main, "_install_hangup_protection", lambda **kwargs: None)
    monkeypatch.setattr(main, "_finalize_update_output", lambda token: None)
    monkeypatch.setattr(update_inventory, "collect_runtime_inventory", lambda: update_inventory.UpdatePlan())
    monkeypatch.setattr(main, "_run_pre_update_backup", lambda args: reached.append("backup"))
    monkeypatch.setattr(main, "_pause_windows_gateways_for_update", lambda: reached.append("pause"))

    # Recreate the former call-site names as tripwires, not host-OS fakes.
    # The scan remains live for lifecycle ownership, but must not gate updates.
    monkeypatch.setattr(update_cmd_windows, "_detect_venv_python_processes", forbidden)
    monkeypatch.setattr(update_cmd, "_refuse_gateway_ancestor_tree_kill", forbidden)
    monkeypatch.setattr(main, "_is_windows", forbidden)
    monkeypatch.setattr(os, "kill", forbidden)

    def prepare_checkout(**_):
        reached.append("checkout")
        raise ReachedCheckout

    monkeypatch.setattr(update_cmd, "_prepare_git_command", prepare_checkout)
    with pytest.raises(ReachedCheckout):
        main.cmd_update(SimpleNamespace(gateway=False, check=False, yes=True, force=False, force_venv=False))
    assert reached == ["backup", "pause", "checkout"]
    forbidden.assert_not_called()

