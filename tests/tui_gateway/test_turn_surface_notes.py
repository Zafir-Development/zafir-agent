"""Per-turn surface notes ride the model input, never the transcript.

``session_notifications._prepend_note`` prefixes what the model must know that
the user did not type (voice-live delegation context, a barge-in mark) onto the
current message. The persisted user row keeps exactly what was typed, so the
frozen system prefix stays byte-stable.
"""

import pytest

from tui_gateway import server


class TestPrepending:
    """Notes ride the model input; the persisted prompt stays what was typed."""

    def test_plain_text_turn(self):
        assert server._prepend_note("go to x", "[Note: hi]") == "[Note: hi]\n\ngo to x"

    def test_multimodal_turn_keeps_its_parts(self):
        parts = [{"type": "text", "text": "go to x"}, {"type": "image_url", "image_url": {}}]

        assert server._prepend_note(parts, "[Note: hi]") == [
            {"type": "text", "text": "[Note: hi]"},
            *parts,
        ]

    def test_nothing_to_say_leaves_the_message_untouched(self):
        parts = [{"type": "text", "text": "go to x"}]

        assert server._prepend_note("go to x", "") == "go to x"
        assert server._prepend_note(parts, "") is parts


class TestSurfaceRecording:
    """``prompt.submit`` stamps the surface each message was typed into."""

    @pytest.fixture
    def busy_session(self):
        import threading

        import types

        # A running session takes the busy path, which returns before any of
        # the agent/DB machinery — enough to observe what submit recorded.
        session = {
            "agent": types.SimpleNamespace(valid_tool_names=set()),
            "session_key": "session-key",
            "history": [],
            "history_lock": threading.Lock(),
            "history_version": 0,
            "running": True,
            "transport": None,
            "attached_images": [],
        }
        server._sessions["sid"] = session
        yield session
        server._sessions.pop("sid", None)

    def _submit(self, **params):
        return server._methods["prompt.submit"](
            "r1", {"session_id": "sid", "text": "what is this?", "queued": True, **params}
        )

    def test_a_live_voice_submit_is_recorded(self, busy_session):
        self._submit(surface="voice-live", voice_context="User: earlier words")

        assert busy_session["client_surface"] == "voice-live"
        assert busy_session["voice_live_context"] == "User: earlier words"

    def test_the_next_typed_submit_clears_it(self, busy_session):
        """A stale surface would tell the model the user is still speaking."""
        self._submit(surface="voice-live", voice_context="User: earlier words")
        self._submit()

        assert busy_session["client_surface"] == ""
        assert busy_session["voice_live_context"] == ""

    def test_an_unknown_surface_is_ignored(self, busy_session):
        self._submit(surface="hud")

        assert busy_session["client_surface"] == ""
