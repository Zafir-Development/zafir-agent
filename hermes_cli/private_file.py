"""Write credential files with owner-only permissions.

POSIX: ``0o600`` via temp file + atomic replace. Windows: mode bits set NO ACLs, so the same
``os.open`` would leave a live session token readable by whatever the inherited DACL grants;
there the file is created through ``CreateFile`` with a protected owner+SYSTEM DACL. ``CreateFile``
ignores the security descriptor when the file already exists, so an existing file is removed first
rather than re-opened — which also avoids ``os.replace`` failing against a reader that still holds
the old file open on Windows.

pywin32 is imported only on Windows.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_OPEN_REPARSE_POINT = 0x00200000


def _win32() -> Any:
    """Namespace of the pywin32 modules used below; import is deferred so this module imports on
    non-Windows hosts."""
    if sys.platform != "win32":
        raise RuntimeError("private credential writers are only available on Windows")
    names = ("ntsecuritycon", "pywintypes", "win32api", "win32con", "win32file", "win32security")
    return SimpleNamespace(**{name: importlib.import_module(name) for name in names})


def _current_sid():
    w = _win32()
    token = w.win32security.OpenProcessToken(w.win32api.GetCurrentProcess(), w.win32con.TOKEN_QUERY)
    return w.win32security.GetTokenInformation(token, w.win32security.TokenUser)[0]


def _system_sid():
    return _win32().win32security.ConvertStringSidToSid("S-1-5-18")


def _sid_str(sid) -> str:
    return _win32().win32security.ConvertSidToStringSid(sid)


def _security_attributes():
    win32security = _win32().win32security
    owner = _sid_str(_current_sid())
    # D:P blocks inherited grants at creation. SDDL also avoids pywin32 311's
    # SetSecurityDescriptorControl argument-width bug on ARM64.
    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        f"O:{owner}D:P(A;;FA;;;{owner})(A;;FA;;;SY)", win32security.SDDL_REVISION_1)
    attributes = win32security.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    return attributes


def _allowed_sids():
    return {_sid_str(_current_sid()), _sid_str(_system_sid())}


def _verify_security(handle) -> None:
    win32security = _win32().win32security
    info = win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION
    descriptor = win32security.GetSecurityInfo(handle, win32security.SE_FILE_OBJECT, info)
    allowed = _allowed_sids()
    if _sid_str(descriptor.GetSecurityDescriptorOwner()) not in allowed:
        raise OSError("private credential file has the wrong owner")
    dacl = descriptor.GetSecurityDescriptorDacl()
    if dacl is None:
        raise OSError("private credential file has a null DACL")
    allow_types = {
        win32security.ACCESS_ALLOWED_ACE_TYPE,
        win32security.ACCESS_ALLOWED_OBJECT_ACE_TYPE,
        getattr(win32security, "ACCESS_ALLOWED_CALLBACK_ACE_TYPE", 9),
        getattr(win32security, "ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE", 11)}
    for index in range(dacl.GetAceCount()):
        ace = dacl.GetAce(index)
        if ace[0][0] in allow_types and ace[1] and _sid_str(ace[-1]) not in allowed:
            raise OSError("private credential file has a permissive DACL")


def _open(path: Path, access: int, creation: int, flags: int, share: int = 0):
    win32file = _win32().win32file
    handle = win32file.CreateFile(str(path), access, share, _security_attributes(), creation, flags, None)
    try:
        actual = win32file.GetFinalPathNameByHandle(handle, 0).removeprefix("\\\\?\\")
        if os.path.normcase(actual) != os.path.normcase(os.path.abspath(str(path))):
            raise OSError("private credential handle escaped its expected path")
        if win32file.GetFileInformationByHandle(handle)[0] & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            raise OSError("private credential path contains a reparse point")
        _verify_security(handle)
        return handle
    except BaseException:
        win32file.CloseHandle(handle)
        raise


def _write_new_windows(path: Path, data: bytes, share: int = 0) -> None:
    w = _win32()
    win32con, win32file = w.win32con, w.win32file
    handle = _open(path, win32con.GENERIC_WRITE | win32con.READ_CONTROL, win32con.CREATE_NEW,
                   win32con.FILE_ATTRIBUTE_NORMAL | _OPEN_REPARSE_POINT, share)
    try:
        win32file.WriteFile(handle, data)
        win32file.FlushFileBuffers(handle)
    finally:
        win32file.CloseHandle(handle)


def write_private_text(path: Path, text: str) -> None:
    """Create/replace ``path`` with owner-only content (``0o600`` on POSIX, owner+SYSTEM DACL on
    Windows)."""
    if sys.platform == "win32":
        with contextlib.suppress(FileNotFoundError):
            os.unlink(str(path))
        _write_new_windows(path, text.encode("utf-8"))
        return
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            with contextlib.suppress(OSError):
                os.fsync(handle.fileno())
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(str(tmp))
        raise
    os.replace(str(tmp), str(path))
