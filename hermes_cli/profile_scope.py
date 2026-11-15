"""Profile, home, secret and config scopes for code acting for a profile other than the launch one.

The gateway's native session listener, the TUI RPC handlers and CLI setup flows all act for one
profile at a time inside a process launched for another. These are the binding seams: the
task-local ``HERMES_HOME`` override, the profile's secret scope, the skills modules' import-time
directory globals, and the config read-modify-write lock shared across worker threads.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Optional

from hermes_cli.config import get_process_hermes_home


class ProfileScopeError(ValueError):
    """A request named a profile that cannot be served: invalid name or missing home.

    ``str(exc)`` keeps the message the profile resolvers produce; the caller decides how to
    surface it (an RPC error, a runtime store error, a printed line).
    """


def _is_current_profile(profile: Optional[str]) -> bool:
    """None/""/"current" all mean this process's own profile."""
    requested = (profile or "").strip()
    return not requested or requested.lower() == "current"


def _resolve_profile_dir(name: str) -> Path:
    """Validate ``name`` and resolve to its directory or raise :class:`ProfileScopeError`."""
    from hermes_cli import profiles as profiles_mod
    try:
        profiles_mod.validate_profile_name(name)
    except ValueError as exc:
        raise ProfileScopeError(str(exc)) from exc
    if not profiles_mod.profile_exists(name):
        raise ProfileScopeError(f"Profile '{name}' does not exist.")
    return profiles_mod.get_profile_dir(name)


@contextmanager
def hermes_home_scope(path) -> Any:
    """Scope ``load_config``/``save_config`` (anything resolving ``get_hermes_home()`` at call
    time) to ``path`` for the block via the context-local HERMES_HOME override."""
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    token = set_hermes_home_override(str(path))
    try:
        yield
    finally:
        reset_hermes_home_override(token)


def serving_profile_name() -> str:
    """This process's OWN profile name — but only when that name provably resolves back
    to the process home.

    Naming the profile explicitly is only safe if the name cannot resolve ELSEWHERE, so a
    custom HERMES_HOME outside ``profiles/`` (``get_active_profile_name()`` answers
    ``"custom"``) returns "" and keeps the unnamed behaviour rather than risking a
    wrong-profile write.
    """
    from hermes_cli import profiles as profiles_mod
    try:
        name = (profiles_mod.get_active_profile_name() or "").strip()
        if not name or name == "custom":
            return ""
        return name if profiles_mod.profile_matches_home(name, get_process_hermes_home()) else ""
    except Exception:  # health: allow BLE001 -- a best-effort name: unreadable profile state keeps the unnamed scope
        return ""


def scope_profile_name(path: Path) -> Optional[str]:
    """Map a profile directory onto the query name :func:`config_profile_scope` expects: None for
    the process home (current-profile semantics: launch secret scope, no home override),
    ``"default"`` for the default root (its basename -- ``.hermes`` or a custom root -- is not a
    profile name; launched from ``profiles/<name>`` the root is a *different* profile), the
    directory name for ``profiles/<name>``."""
    from hermes_constants import get_default_hermes_root
    resolved = path.resolve()
    if resolved == get_process_hermes_home().resolve():
        return None
    if resolved == get_default_hermes_root().resolve():
        return "default"
    return path.name


# Skills modules bind HERMES_HOME / SKILLS_DIR at import time, so retargeting them is a
# process-global swap that must not interleave between threads.
_SKILLS_PROFILE_LOCK = threading.RLock()


@contextmanager
def profile_scope(profile: Optional[str]):
    """Scope config + skill-directory resolution to ``profile`` for one operation.

    Two seams: (1) ``load_config``/``save_config`` resolve ``get_hermes_home()`` at call
    time, so the contextvar override reaches them; (2) ``tools.skills_tool`` /
    ``tools.skill_manager_tool`` bind ``SKILLS_DIR`` at import time, so both are retargeted
    under a lock and restored after. For the process's own profile config resolution is
    untouched, but the skill-module globals are still retargeted to the *current*
    ``get_hermes_home()`` so writes land in the live home even when the import-time binding
    is stale (test isolation, late HERMES_HOME override). Yields the profile dir for a named
    profile, None for the current one.

    ``tools.skills_sync`` (reset/diff/list-modified/opt-in/opt-out/repair-official) needs NO
    retargeting: its directory lookups resolve at call time through the same contextvar
    override set in step 1.
    """
    from hermes_constants import get_hermes_home
    from tools import skills_tool as _skills_tool
    from tools import skill_manager_tool as _skill_mgr
    with config_profile_scope(profile) as scoped:
        profile_dir = get_hermes_home() if scoped is None else scoped
        modules = (_skills_tool, _skill_mgr)
        with _SKILLS_PROFILE_LOCK:
            saved = [(m.HERMES_HOME, m.SKILLS_DIR) for m in modules]
            for m in modules:
                m.HERMES_HOME, m.SKILLS_DIR = profile_dir, profile_dir / "skills"
            try:
                yield scoped
            finally:
                for m, (home, skills_dir) in zip(modules, saved):
                    m.HERMES_HOME, m.SKILLS_DIR = home, skills_dir


@contextmanager
def config_profile_scope(profile: Optional[str]):
    """Await-safe profile scope: the task-local HERMES_HOME contextvar PLUS the profile's secret
    scope, never the process-global skills-module attributes :func:`profile_scope` swaps
    (holding those across an ``await`` lets a concurrent task restore THIS task's dir on its
    ``finally``). None/""/"current" = no override.

    Home alone leaves ``get_secret`` on the process's ``os.environ`` — the DEFAULT profile's
    values — so a read scoped to profile B would expand B's ``${VAR}`` refs to the default
    profile's plaintext credentials and bridge B's YAML settings into the shared process env
    (``yaml_env_setter`` skips only under a secret scope). A named profile's home also flips
    this process to fail-closed multi-profile hosting
    (``tui_gateway/launch_profile_policy.py``), so any remaining unscoped read raises instead
    of borrowing.

    Explicit names resolving to the process home retain current-profile semantics.
    None/""/"current" mean the effective home: a task-local override (a secondary profile's
    native ticket, ``native_profile_scope``) is that profile, so it gets that profile's secret
    scope rather than the launch profile's.
    """
    from agent.secret_scope import build_profile_secret_scope, reset_secret_scope, set_secret_scope
    from hermes_cli.env_loader import hydrate_profile_secret_sources
    from hermes_constants import get_hermes_home, get_hermes_home_override
    from tui_gateway.launch_profile_policy import activate_multi_profile_hosting, launch_secret_scope

    process_home = get_process_hermes_home()
    if _is_current_profile(profile):
        profile_dir = get_hermes_home() if get_hermes_home_override() else None
    else:
        profile_dir = _resolve_profile_dir(profile.strip())
    scoped = None if profile_dir is None or profile_dir.resolve() == process_home.resolve() else profile_dir
    if scoped is not None:
        activate_multi_profile_hosting()
        hydrate_profile_secret_sources(scoped)  # first call may block on the source's fetch
        secrets = build_profile_secret_scope(scoped)
    else:
        # The process's own profile: its launch-env scope (live env + .env while single-profile, so
        # systemd / op-run injection keeps resolving; frozen at activation afterwards). Bound even
        # before any secondary is served so the credential source is decided HERE: a concurrent
        # first ``?profile=B`` read flips ``get_secret`` to fail closed mid-read, and an unscoped
        # launch read would then raise ``UnscopedSecretError`` on its next lookup.
        secrets = launch_secret_scope(process_home)
    with (hermes_home_scope(profile_dir) if profile_dir is not None else nullcontext()):
        token = set_secret_scope(secrets, profile_home=str(profile_dir or process_home))
        try:
            yield scoped
        finally:
            reset_secret_scope(token)


# Serializes config.yaml read-modify-write cycles for callers on worker threads:
# config.py's _CONFIG_LOCK covers each load/save call, not the span between them, so two
# off-loop updates could drop each other's writes. RLock so nested helpers that also take it
# can't self-deadlock.
CONFIG_MUTATION_LOCK = threading.RLock()


@contextmanager
def config_write_scope(profile: Optional[str]):
    """Profile scope, then the config mutation lock — the write-path nesting every
    config-mutating caller uses."""
    with profile_scope(profile):
        with CONFIG_MUTATION_LOCK:
            yield
