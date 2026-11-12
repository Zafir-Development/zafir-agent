"""Windows confidentiality for the host rendezvous token + lock (``platforms("windows")``).

``os.open(..., 0o600)`` sets NO ACLs on Windows, so the host token — which holds the backend's
LIVE session token — would inherit whatever the parent directory grants.
``hermes_cli.private_file.write_private_text`` is the repo's primitive for this credential class;
this proves the host rendezvous actually uses it, and that the host lock still works on that path.
"""

import pytest

from gateway import host_rendezvous as hr

pytestmark = pytest.mark.platforms("windows")


@pytest.fixture
def host_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_GATEWAY_LOCK_DIR", str(tmp_path / "locks"))
    yield tmp_path
    hr.release_host_lock(hr.ROLE_GATEWAY)


def _assert_private_dacl(path):
    import ntsecuritycon
    import win32security

    from hermes_cli import private_file as pf

    descriptor = win32security.GetFileSecurity(
        str(path), win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION)
    assert pf._sid_str(descriptor.GetSecurityDescriptorOwner()) == pf._sid_str(pf._current_sid())
    dacl = descriptor.GetSecurityDescriptorDacl()
    assert dacl is not None, "a null DACL grants everyone"
    granted = set()
    for index in range(dacl.GetAceCount()):
        ace = dacl.GetAce(index)
        assert ace[0] == (win32security.ACCESS_ALLOWED_ACE_TYPE, 0)
        assert ace[1] == ntsecuritycon.FILE_ALL_ACCESS
        granted.add(pf._sid_str(ace[-1]))
    assert granted == pf._allowed_sids()
    assert descriptor.GetSecurityDescriptorControl()[0] & win32security.SE_DACL_PROTECTED


def test_host_token_is_written_with_a_protected_owner_only_dacl(host_dir):
    """Owner+SYSTEM only, and the DACL is protected so inheritable parent grants are not merged."""
    assert hr.claim_host_lock(hr.ROLE_GATEWAY)[0] is hr.HostLockOutcome.ACQUIRED
    hr.publish_record(hr.ROLE_GATEWAY, host="127.0.0.1", port=9119, token="live-session-token")

    path = hr.token_path(hr.ROLE_GATEWAY)
    assert path.read_text(encoding="utf-8-sig").strip() == "live-session-token"
    _assert_private_dacl(path)


def test_rewriting_an_existing_token_keeps_it_private(host_dir):
    """CreateFile ignores creation security on existing files; replacement must repair old grants."""
    import ntsecuritycon
    import win32security

    assert hr.claim_host_lock(hr.ROLE_GATEWAY)[0] is hr.HostLockOutcome.ACQUIRED
    hr.publish_record(hr.ROLE_GATEWAY, host="127.0.0.1", port=9119, token="first")
    path = hr.token_path(hr.ROLE_GATEWAY)
    permissive = win32security.ACL()
    permissive.AddAccessAllowedAceEx(
        win32security.ACL_REVISION, 0, ntsecuritycon.FILE_ALL_ACCESS,
        win32security.ConvertStringSidToSid("S-1-1-0"))
    win32security.SetNamedSecurityInfo(
        str(path), win32security.SE_FILE_OBJECT, win32security.DACL_SECURITY_INFORMATION,
        None, None, permissive, None)

    hr.publish_record(hr.ROLE_GATEWAY, host="127.0.0.1", port=9119, token="second")

    assert hr.read_token(hr.ROLE_GATEWAY) == "second"
    _assert_private_dacl(path)
    record = hr.read_record(hr.ROLE_GATEWAY, include_stale=True)
    assert record is not None and hr.record_token_is_consistent(record)
