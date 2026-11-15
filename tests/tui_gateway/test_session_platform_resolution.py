"""Platform/source tagging for a ``tui_gateway`` session.

The backend serves the TUI; there is no env-selected graphical chat surface any
more, so the resolvers always answer ``tui`` unless the caller passes an explicit
source (a plugin's ``"telegram"`` session keeps its own tag). The Desktop env
vars must not resurrect a desktop platform.
"""

import pytest


def _reload_resolver():
    # Plain import — every resolver under test reads the env at CALL time, so
    # no reload is needed. importlib.reload(tui_gateway.server) would
    # re-register the module's atexit hooks (thread-pool shutdown +
    # _shutdown_sessions) on every test; duplicated hooks race the stderr
    # buffer at interpreter shutdown (Fatal Python error:
    # _enter_buffered_busy) — same flake class as PR #34217. Name kept for
    # the existing call sites.
    import tui_gateway.server as _srv
    return _srv


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("HERMES_DESKTOP", raising=False)
    monkeypatch.delenv("HERMES_DESKTOP_TERMINAL", raising=False)
    return monkeypatch


class TestResolveSessionPlatform:
    def test_standalone_tui_neither_env_set(self, clean_env):
        _srv = _reload_resolver()
        assert _srv._resolve_session_platform() == "tui"

    def test_desktop_env_no_longer_selects_a_platform(self, clean_env):
        """The Desktop chat platform is gone: its env marker grants nothing."""
        clean_env.setenv("HERMES_DESKTOP", "1")
        clean_env.setenv("HERMES_DESKTOP_TERMINAL", "true")
        _srv = _reload_resolver()
        assert _srv._resolve_session_platform() == "tui"


class TestResolveSessionSource:
    def test_explicit_source_param_wins(self, clean_env):
        _srv = _reload_resolver()
        assert _srv._resolve_session_source("telegram") == "telegram"

    def test_no_env_no_param_defaults_to_tui(self, clean_env):
        _srv = _reload_resolver()
        assert _srv._resolve_session_source(None) == "tui"


class TestResolveAgentPlatform:
    def test_missing_source_falls_back_to_the_tui(self, clean_env):
        clean_env.setenv("HERMES_DESKTOP", "1")
        _srv = _reload_resolver()
        assert _srv._resolve_agent_platform(None) == "tui"

    def test_explicit_source_is_not_rewritten(self, clean_env):
        _srv = _reload_resolver()
        assert _srv._resolve_agent_platform("acp") == "acp"


class TestSessionSourceFallback:
    def test_session_source_uses_existing_session_value(self, clean_env):
        clean_env.setenv("HERMES_DESKTOP", "1")
        _srv = _reload_resolver()
        assert _srv._session_source({"source": "telegram"}) == "telegram"

    def test_session_without_a_source_falls_back_to_the_tui(self, clean_env):
        clean_env.setenv("HERMES_DESKTOP", "1")
        _srv = _reload_resolver()
        assert _srv._session_source({}) == "tui"
