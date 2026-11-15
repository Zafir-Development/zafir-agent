"""Local-model job progress accounting."""

from __future__ import annotations

from collections import deque


def test_rate_and_eta_report_only_an_honest_number():
    """Rate is the slope across the window; anything unmeasurable is unknown.

    A fabricated rate would render as a confident ETA that keeps being wrong,
    so a single sample, a window too short to divide by, and a stalled
    transfer must all report (None, None) rather than a guess.
    """
    from hermes_cli.local_models_service import _rate_and_eta

    mib = 1 << 20
    assert _rate_and_eta(deque([(0.0, 0), (1.0, mib)]), mib, 3 * mib) == (float(mib), 2)
    assert _rate_and_eta(deque([(0.0, 0)]), 0, 100) == (None, None)
    assert _rate_and_eta(deque([(0.0, 0), (0.1, 50)]), 50, 100) == (None, None)
    assert _rate_and_eta(deque([(0.0, 40), (1.0, 40)]), 40, 100) == (None, None)
    # A rate with no denominator: ETA stays unknown, speed still useful.
    assert _rate_and_eta(deque([(0.0, 0), (1.0, mib)]), mib, None) == (float(mib), None)
