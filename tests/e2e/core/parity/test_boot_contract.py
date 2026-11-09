"""Backend boot handshake contract, Python side (issue class C5).

``hermes serve`` is spawned with stdout piped and announces the port it bound ONLY on
the READY sentinel line; the Ink TUI spawns ``tui_gateway.entry`` and treats stdout as
a pure JSON-RPC stream whose first frame is ``gateway.ready``. Both break the same way —
the sentinel/frame goes to the wrong stream, arrives after other bytes, or stops
parsing — and every such break presents to users as "backend failed to start" / a hung
spinner.

Invariants (spawned cold, fake provider):

* serve: the FIRST stdout line is the sentinel naming a port, and that port is the live
  backend (authenticated ``/api/status`` answers).
* tui_gateway: the FIRST stdout line is a JSON-RPC ``gateway.ready`` event whose
  payload validates against the published contract, and every later stdout line
  is JSON-RPC too (stray prints must land on stderr).
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from tests.e2e.core.parity._drive_rpc import (
    READY_TIMEOUT,
    RpcClient,
    first_stdout_line,
    spawn_serve,
    spawn_tui_gateway,
)
from tests.e2e.core.parity._helpers import build_parity_home, kill_tagged, start_provider, terminate

# The machine-readable boot line: nothing may precede it on stdout.
READY_LINE_RE = re.compile(r"^HERMES_BACKEND_READY port=(\d+)$")

# Linux-only (/proc process-tree scans). The live-system guard bypass is needed
# ONLY for teardown: orphans reparented to init (the exact failure this suite
# hunts) sit outside the pytest subtree, and kill_tagged() signals nothing but
# PIDs carrying this run's unique PARITY_TREE_TAG. Children run with a tmp
# HOME/HERMES_HOME (asserted in ParityHome.env), so no real state is reachable.
pytestmark = [
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="process-tree cleanup uses /proc"),
    pytest.mark.live_system_guard_bypass,
]


@contextlib.contextmanager
def boot_home(tmp_path: Path):
    # A context manager used INSIDE the test body, not a fixture: the orphan sweep
    # must run while the test's live-guard bypass is still in effect.
    srv = start_provider("boot")
    ph = build_parity_home(tmp_path, srv.base_url)
    try:
        yield ph
    finally:
        kill_tagged(ph)
        srv.stop()


def test_serve_ready_sentinel_is_first_stdout_line_and_names_the_live_port(tmp_path: Path) -> None:
    with boot_home(tmp_path) as home:
        _check_serve_ready(home)


def _check_serve_ready(home) -> None:
    sp = spawn_serve(home)
    try:
        first = first_stdout_line(sp)
        match = READY_LINE_RE.match(first.strip())
        assert match, (
            f"first stdout line is not a READY sentinel: {first!r}\n"
            f"(stdout must carry nothing before READY)\nstderr tail:\n{sp.cap.stderr[-1500:]}")
        port = int(match.group(1))

        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status",
                                     headers={"X-Hermes-Session-Token": sp.token})
        with urllib.request.urlopen(req, timeout=30) as resp:
            assert resp.status == 200, resp.status
            json.loads(resp.read())
    finally:
        terminate(sp.proc, timeout=60)


def test_tui_gateway_first_stdout_frame_is_contract_valid_gateway_ready(tmp_path: Path) -> None:
    with boot_home(tmp_path) as home:
        _check_tui_gateway_ready(home)


def _check_tui_gateway_ready(home) -> None:
    from tui_gateway.contracts.registry import EVENTS

    proc, cap = spawn_tui_gateway(home)
    try:
        deadline = time.monotonic() + READY_TIMEOUT
        while not cap.stdout_seen:
            assert proc.poll() is None, f"tui_gateway exited {proc.returncode}\n{cap.stderr[-2000:]}"
            assert time.monotonic() < deadline, f"no stdout frame within {READY_TIMEOUT}s\n{cap.stderr[-2000:]}"
            time.sleep(0.05)
        first = cap.stdout_seen[0]
        try:
            frame = json.loads(first)
        except ValueError:
            frame = None
        assert isinstance(frame, dict), f"first stdout line of tui_gateway is not JSON-RPC: {first!r}"
        params = frame.get("params") or {}
        assert frame.get("method") == "event" and params.get("type") == "gateway.ready", frame
        ready = EVENTS["gateway.ready"]
        if ready.payload is not None:
            ready.payload.model_validate(params.get("payload") or {})

        # Exercise one RPC so post-ready output has a chance to leak, then check
        # the whole stream stayed JSON-RPC.
        def send(line: str) -> None:
            assert proc.stdin is not None
            proc.stdin.write(line + "\n")
            proc.stdin.flush()

        rpc = RpcClient(send, cap.stdout_lines)
        rpc.call("session.create", {}, timeout=READY_TIMEOUT)
        for line in list(cap.stdout_seen):
            try:
                assert json.loads(line).get("jsonrpc") == "2.0"
            except ValueError:
                pytest.fail(f"non-JSON bytes on tui_gateway stdout: {line!r}")
    finally:
        if proc.stdin is not None and not proc.stdin.closed:
            proc.stdin.close()
        try:
            proc.wait(timeout=60)
        except Exception:
            terminate(proc)
