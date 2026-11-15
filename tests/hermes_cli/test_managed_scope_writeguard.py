"""Write-guard tests — managed keys can't be set/removed by the user."""
import pytest


@pytest.fixture
def homes(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    managed = tmp_path / "managed"
    managed.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    import hermes_cli.config as cfg
    from hermes_cli import managed_scope

    cfg._LOAD_CONFIG_CACHE.clear()
    cfg._RAW_CONFIG_CACHE.clear()
    managed_scope.invalidate_managed_cache()
    (managed / "config.yaml").write_text(
        "model:\n  default: managed/model\n", encoding="utf-8"
    )
    managed_scope.invalidate_managed_cache()
    return home, managed


def test_config_set_managed_key_rejected(homes, capsys):
    from hermes_cli.config import set_config_value

    with pytest.raises(SystemExit) as exc:
        set_config_value("model.default", "user/override")
    assert exc.value.code != 0
    captured = capsys.readouterr()
    assert "managed" in (captured.out + captured.err).lower()




# ── env write guards ─────────────────────────────────────────────────────────


@pytest.fixture
def env_homes(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    managed = tmp_path / "managed"
    managed.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    (managed / ".env").write_text(
        "OPENAI_API_BASE=https://org.example/v1\n", encoding="utf-8"
    )
    from hermes_cli import managed_scope

    managed_scope.invalidate_managed_cache()
    return home, managed


def test_save_env_value_managed_key_rejected(env_homes, capsys):
    from hermes_cli.config import save_env_value, get_env_path

    save_env_value("OPENAI_API_BASE", "https://user.example/v1")
    assert "managed" in capsys.readouterr().err.lower()
    env_path = get_env_path()
    body = env_path.read_text() if env_path.exists() else ""
    assert "user.example" not in body


# Runtime-constructed fake credentials (never literal key-shaped strings).
OLD_KEY = "sk-ds-" + "b" * 24


_ANTHROPIC_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")


@pytest.fixture
def anthropic_homes(tmp_path, monkeypatch):
    """A user home whose auth.json holds a manually added anthropic key, and an empty managed dir."""
    import json

    import hermes_cli.config as cfg
    from hermes_cli import managed_scope

    home, managed = tmp_path / "home", tmp_path / "managed"
    home.mkdir()
    managed.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    for name in _ANTHROPIC_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    (home / "auth.json").write_text(json.dumps({"credential_pool": {"anthropic": [{
        "id": "m1", "label": "manual", "auth_type": "api_key", "priority": 0,
        "source": "manual", "access_token": OLD_KEY}]}}), encoding="utf-8")

    def reload():
        cfg.invalidate_env_cache()
        managed_scope.invalidate_managed_cache()

    reload()
    return home, managed, reload


def _disconnect(slug):
    from tui_gateway import server

    return server._methods["model.disconnect"](1, {"slug": slug})


def test_disconnect_on_a_package_managed_install_still_clears_the_auth_store(anthropic_homes, monkeypatch):
    """The .env lock refuses every key on such an install, but a key that holds nothing is nothing to refuse."""
    import json

    home, _managed, _reload = anthropic_homes
    monkeypatch.setenv("HERMES_MANAGED", "nixos")
    resp = _disconnect("anthropic")
    assert resp.get("result", {}).get("disconnected") is True, resp
    assert "anthropic" not in json.loads((home / "auth.json").read_text(encoding="utf-8"))["credential_pool"]


# ── bulk save strips managed leaves ──────────────────────────────────────────


