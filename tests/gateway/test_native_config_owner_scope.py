"""A native listener binds the served profile's home even when a foreign home override is ambient."""
from pathlib import Path


def test_launch_ticket_overrides_foreign_ambient_scope(tmp_path, monkeypatch):
    from agent.secret_scope import get_secret
    from hermes_cli.profile_scope import config_profile_scope, hermes_home_scope
    from hermes_constants import get_hermes_home, reset_hermes_home_override, set_hermes_home_override
    home = tmp_path / '.hermes'
    home.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('SCOPE_SENTINEL', 'launch')
    beta = home / 'profiles' / 'beta'
    beta.mkdir(parents=True)
    (beta / '.env').write_text('SCOPE_SENTINEL=beta\n', encoding='utf-8')
    ambient = set_hermes_home_override(str(beta))
    try:
        # The listener redeems a ticket for the home it serves and dispatches under that home's
        # scope: an ambient (foreign) override cannot redirect config or secret reads.
        with hermes_home_scope(home), config_profile_scope(None):
            seen = (get_hermes_home(), get_secret('SCOPE_SENTINEL'))
    finally:
        reset_hermes_home_override(ambient)
    assert seen == (home, 'launch')
