"""Discovery authorizes the caller before scanning skills or plugin commands."""
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_discovery_authorizes_before_scanning(tmp_path, monkeypatch):
    from agent import skill_commands
    from hermes_cli import plugins
    from gateway.session_controls import AuthorityConnection

    def forbidden(*args, **kwargs):
        pytest.fail('unauthorized request reached discovery')
    monkeypatch.setattr(skill_commands, 'scan_skill_commands', forbidden)
    monkeypatch.setattr(plugins, 'get_plugin_commands', forbidden)
    authority = SimpleNamespace(instance_id='owned', profile_id=str(tmp_path), events={})
    for identity in ({}, {'user_id': 'reader', 'capabilities': []},
                     {'user_id': 'reader', 'profile_id': 'foreign'},
                     {'user_id': 'reader', 'instance_id': 'stale'}):
        connection = AuthorityConnection(authority, object(), identity)
        try:
            for method in ('commands.catalog', 'complete.slash'):
                reply = await connection.dispatch({'id': 1, 'method': method,
                    'params': {'text': '/probe'} if method == 'complete.slash' else {}})
                assert reply['error']['message'] == 'permission_denied', reply
        finally:
            await connection.close()
