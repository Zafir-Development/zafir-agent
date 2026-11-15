"""The CLI gateway-restart flow refuses BEFORE it stops anything (#125394, #77276).

``hermes gateway restart`` used to reap "orphan" gateways before dispatching the
restart; when the child then refused (a named profile under the host multiplexer)
the profile had already lost its gateway. The reap belongs to the child, after
its refusal guard.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from hermes_cli import gateway as gw


def test_cli_restart_reaps_after_the_refusal_guard(monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(gw, "_refuse_from_inside_gateway", lambda *a, **k: None)
    monkeypatch.setattr(gw, "_guard_named_profile_under_multiplexer", lambda **k: order.append("guard"))
    monkeypatch.setattr(gw, "_dispatch_via_service_manager_if_s6", lambda *a, **k: False)
    monkeypatch.setattr(gw, "_installed_service_kind_for", lambda windows: "launchd")
    monkeypatch.setattr(gw, "_reap_unsupervised_gateway_orphans", lambda *a, **k: order.append("reap"))
    monkeypatch.setattr(gw, "_service_call", lambda *a, **k: order.append("restart"))

    gw._cmd_restart(SimpleNamespace(system=False, all=False, force=False))

    assert order == ["guard", "reap", "restart"]


def test_cli_restart_reap_failure_does_not_block_restart(monkeypatch):
    """The reap is best-effort: a scan error must not abort the restart it precedes."""
    order: list[str] = []
    monkeypatch.setattr(gw, "_refuse_from_inside_gateway", lambda *a, **k: None)
    monkeypatch.setattr(gw, "_guard_named_profile_under_multiplexer", lambda **k: None)
    monkeypatch.setattr(gw, "_dispatch_via_service_manager_if_s6", lambda *a, **k: False)
    monkeypatch.setattr(gw, "_installed_service_kind_for", lambda windows: "launchd")

    def _boom(*a, **k):
        raise OSError("permission denied")

    monkeypatch.setattr(gw, "_reap_unsupervised_gateway_orphans", _boom)
    monkeypatch.setattr(gw, "_service_call", lambda *a, **k: order.append("restart"))

    gw._cmd_restart(SimpleNamespace(system=False, all=False, force=False))

    assert order == ["restart"]
