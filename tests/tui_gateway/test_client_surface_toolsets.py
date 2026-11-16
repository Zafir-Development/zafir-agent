"""The client-surface toolsets a TUI session carries.

The TUI is the client: its own toolset bundle (``CLIENT_SURFACE_TOOLSETS``)
folds into every session whatever the config says, because only that surface
can answer those tools. The desktop-only bundles (``desktop_ui``, ``catalog``,
``onboarding``) and their tools are gone; a disabled name is still subtracted
from the fold-in and an operator ``HERMES_TUI_TOOLSETS`` pin still wins.
"""

import pytest

from toolsets import CLIENT_SURFACE_TOOLSETS, TOOLSETS


@pytest.fixture
def clean_env(monkeypatch):
    """A backend nobody told about the desktop."""
    monkeypatch.delenv("HERMES_DESKTOP", raising=False)
    monkeypatch.delenv("HERMES_DESKTOP_TERMINAL", raising=False)
    monkeypatch.delenv("HERMES_TUI_TOOLSETS", raising=False)
    return monkeypatch


class TestClientSurfaceBundle:

    def test_the_client_surface_is_the_project_bundle(self):
        """The TUI carries Projects, and only Projects, off the core tool list."""
        from toolsets import _HERMES_CORE_TOOLS

        assert "project" in CLIENT_SURFACE_TOOLSETS
        assert CLIENT_SURFACE_TOOLSETS.isdisjoint(_HERMES_CORE_TOOLS)

    def test_every_client_surface_toolset_resolves(self):
        from toolsets import validate_toolset

        for name in CLIENT_SURFACE_TOOLSETS:
            assert validate_toolset(name), name

    @pytest.mark.parametrize("removed", ["desktop_ui", "catalog", "onboarding"])
    def test_removed_renderer_toolsets_are_not_registered(self, removed):
        assert removed not in TOOLSETS

    def test_the_session_carries_the_client_surface_with_no_desktop_env(self, clean_env):
        from tui_gateway import server

        assert "project" in server._client_surface_toolsets()


class TestResolverPlumbing:
    def test_posture_path_folds_in_the_session_surface(self, clean_env):
        """Focus-mode returns early — the client-surface toolsets must survive it."""
        import agent.coding_context as cc
        from tui_gateway import server

        clean_env.setattr(cc, "coding_selection", lambda **_: ["coding"])

        assert server._load_enabled_toolsets("tui") == ["coding", "project"]

    def test_config_path_folds_in_the_session_surface(self, clean_env):
        import agent.coding_context as cc
        import hermes_cli.config as config_mod
        from tui_gateway import server

        clean_env.setattr(cc, "coding_selection", lambda **_: None)
        clean_env.setattr(
            config_mod, "load_config", lambda: {"platform_toolsets": {"cli": ["memory"]}}
        )

        tui = server._load_enabled_toolsets("tui")

        assert tui is not None
        assert "memory" in tui and "project" in tui

    def test_desktop_env_no_longer_changes_the_selection(self, clean_env):
        import agent.coding_context as cc
        from tui_gateway import server

        clean_env.setattr(cc, "coding_selection", lambda **_: ["coding"])
        clean_env.setenv("HERMES_DESKTOP", "1")
        clean_env.setenv("HERMES_DESKTOP_TERMINAL", "1")

        assert server._load_enabled_toolsets("tui") == ["coding", "project"]

    def test_a_disabled_client_toolset_is_subtracted(self, clean_env, monkeypatch):
        from tui_gateway import server

        monkeypatch.setattr(server, "_load_disabled_toolsets", lambda: ["project"])

        assert server._with_session_toolsets(["memory"], "tui") == ["memory"]

    def test_explicit_env_pin_still_wins(self, clean_env):
        """HERMES_TUI_TOOLSETS is an operator override; surface can't re-add."""
        from tui_gateway import server

        clean_env.setenv("HERMES_TUI_TOOLSETS", "web,memory")

        assert server._load_enabled_toolsets("tui") == ["web", "memory"]


class TestExplicitEmptySelection:
    """#82010: an explicitly saved empty platform_toolsets list is a zero-tool state.

    ``platform_toolsets.cli: []`` used to fall open — the resolver returned an empty set and
    the gateway converted it to None, which downstream means 'no restriction' (every
    toolset). Only an ABSENT key means that; the explicit empty list must return [].
    """

    @staticmethod
    def _config(clean_env, platform_toolsets):
        import agent.coding_context as cc
        import hermes_cli.config as config_mod

        clean_env.setattr(cc, "coding_selection", lambda **_: None)
        clean_env.setattr(
            config_mod, "load_config", lambda: {"platform_toolsets": platform_toolsets}
        )

    def test_explicit_empty_list_yields_no_toolsets(self, clean_env):
        from tui_gateway import server

        self._config(clean_env, {"cli": []})

        assert server._load_enabled_toolsets("tui") == []

    def test_absent_key_keeps_the_default_selection(self, clean_env):
        from tui_gateway import server

        self._config(clean_env, {})

        result = server._load_enabled_toolsets("tui")
        assert result  # the platform default applies — not the zero state, not None-as-all

    def test_named_selection_is_honored(self, clean_env):
        from tui_gateway import server

        self._config(clean_env, {"cli": ["memory"]})

        result = server._load_enabled_toolsets("tui")
        assert result is not None
        assert "memory" in result
        assert "terminal" not in result
