"""Tests for the SessionTokenProvider plugin (the deployment session token as a
gated-mode credential).

Loads the bundled session_token plugin module directly and exercises
``verify_session`` — constant-time accept of the provisioned token into a
Session, None for anything else; refresh/revoke/start_login semantics.
"""
from __future__ import annotations

import secrets

import pytest

import plugins.dashboard_auth.session_token as session_token_plugin
from hermes_cli.dashboard_auth import RefreshExpiredError, assert_protocol_compliance
from hermes_cli.dashboard_auth import registry


@pytest.fixture(scope="module")
def plugin():
    return session_token_plugin


@pytest.fixture(autouse=True)
def _clean_env_and_registry(monkeypatch):
    monkeypatch.delenv("HERMES_DASHBOARD_SESSION_TOKEN", raising=False)
    registry.clear_providers()
    yield
    registry.clear_providers()


def _token() -> str:
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Provider behaviour
# ---------------------------------------------------------------------------


class TestProvider:
    def test_protocol_compliance(self, plugin):
        assert_protocol_compliance(plugin.SessionTokenProvider)

    def test_is_a_session_credential_but_not_an_interactive_login(self, plugin):
        p = plugin.SessionTokenProvider(token=_token())
        assert p.supports_session is True
        assert p.supports_password is False
        assert p.interactive_login is False

    def test_verify_session_accepts_the_provisioned_token(self, plugin):
        token = _token()
        p = plugin.SessionTokenProvider(token=token)
        session = p.verify_session(access_token=token)
        assert session is not None
        assert session.provider == "session-token"
        assert session.user_id == "deployment-token"
        assert session.access_token == token
        assert session.expires_at > 0

    def test_verify_session_rejects_foreign_and_empty(self, plugin):
        p = plugin.SessionTokenProvider(token=_token())
        assert p.verify_session(access_token=secrets.token_urlsafe(32)) is None
        assert p.verify_session(access_token="") is None

    def test_refresh_raises_expired_and_revoke_is_silent(self, plugin):
        p = plugin.SessionTokenProvider(token=_token())
        with pytest.raises(RefreshExpiredError):
            p.refresh_session(refresh_token="anything")
        assert p.revoke_session(refresh_token="anything") is None

    def test_interactive_methods_raise(self, plugin):
        p = plugin.SessionTokenProvider(token=_token())
        with pytest.raises(NotImplementedError):
            p.start_login(redirect_uri="r")
        with pytest.raises(NotImplementedError):
            p.complete_login(code="c", state="s", code_verifier="v", redirect_uri="r")

    def test_construction_rejects_empty_token(self, plugin):
        with pytest.raises(ValueError):
            plugin.SessionTokenProvider(token="")

