"""The Nous Portal client the listener this process serves signs in with instead of the configured one.

Plugin discovery imports the bundled Nous sign-in plugin under a module name of its own, so the
plugin and this process meet here: the plugin offers its provider swap when discovery loads it
(:func:`offer`), and reads :func:`current` whenever it builds its provider, a plugin reload
included. No listener registers its own client any more, so :func:`current` is always None and the
configured ``HERMES_DASHBOARD_OAUTH_CLIENT_ID`` is what the plugin signs in with.
"""
from __future__ import annotations

from typing import Callable, Optional

_current: Optional[tuple[str, str]] = None


def current() -> Optional[tuple[str, str]]:
    """``(client_id, portal_url)`` while a listener signs in with its own client, else None."""
    return _current


def offer(swap: Callable[[], Callable[[], None]]) -> None:
    """Called by the Nous sign-in plugin as discovery loads it; the swap is never engaged."""
