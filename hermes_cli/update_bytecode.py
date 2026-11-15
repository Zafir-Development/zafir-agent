"""Checkout bytecode hygiene: the launch sweep and the dropped-directory prune.

Names that still live in ``hermes_cli/main.py`` (``PROJECT_ROOT``, ...) are imported lazily
inside the functions that use them (avoids an import cycle).
"""

import logging
import os
import subprocess
import sys

from pathlib import Path

# Log-record parity with the origin module.
logger = logging.getLogger("hermes_cli.main")

# Checkout fingerprint the bytecode cache was last validated against. Lives next
# to the checkout (NOT in HERMES_HOME): __pycache__ is per-checkout state shared
# by every profile.
_BYTECODE_FINGERPRINT_FILE = ".bytecode-fingerprint"


def _record_bytecode_fingerprint() -> None:
    """Persist the current checkout fingerprint after a bytecode sweep. Never raises."""
    from hermes_cli.main import PROJECT_ROOT, _read_git_revision_fingerprint
    try:
        fingerprint = _read_git_revision_fingerprint(PROJECT_ROOT)
        if not fingerprint:
            return
        stamp_path = PROJECT_ROOT / _BYTECODE_FINGERPRINT_FILE
        tmp_path = stamp_path.with_name(stamp_path.name + ".tmp")
        tmp_path.write_text(fingerprint, encoding="utf-8")
        tmp_path.replace(stamp_path)
    except OSError as exc:
        logger.debug("Could not record bytecode fingerprint: %s", exc)


def _recorded_bytecode_fingerprint(root: Path) -> str:
    try:
        return (root / _BYTECODE_FINGERPRINT_FILE).read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""


def _prune_dropped_directories(root: Path, recorded_fingerprint: str) -> int:
    """Remove the directories left empty by files the checkout dropped since ``recorded_fingerprint``.

    Git deletes a dropped file but keeps its directory while ``__pycache__`` is in it, and the
    bytecode sweep then leaves it empty. An empty directory at an old package path imports as an
    empty namespace package and hides the package's new location. Run after the bytecode sweep.
    Only empty directories are removed (``rmdir``), never one reached through a symlink, so one
    holding any other file stays. Returns the number removed; nothing is removed when the recorded
    commit is unknown or no longer in the repository. Raises ``OSError`` when git cannot list the
    dropped files, so the caller keeps the old fingerprint and the next sweep retries.
    """
    from hermes_cli._early_recovery import is_object_id
    from hermes_cli._subprocess_compat import windows_hide_flags

    since = recorded_fingerprint.rpartition(":")[2]
    if not is_object_id(since):
        return 0
    git = ["git", "-C", str(root)]
    try:
        known = subprocess.run([*git, "cat-file", "-e", f"{since}^{{commit}}"], capture_output=True,
                               stdin=subprocess.DEVNULL, timeout=60, creationflags=windows_hide_flags(), check=False)
        if known.returncode != 0:
            return 0  # the recorded commit is gone (gc, re-clone): nothing to diff against, ever
        listed = subprocess.run(
            [*git, "diff", "--name-only", "--no-renames", "--diff-filter=D", "-z", since, "HEAD"],
            capture_output=True, stdin=subprocess.DEVNULL, timeout=60,
            creationflags=windows_hide_flags(), check=False)
    except subprocess.SubprocessError as exc:
        raise OSError(f"could not list the files dropped since {since[:10]}: {exc}") from exc
    if listed.returncode != 0:
        raise OSError(f"could not list the files dropped since {since[:10]}: git exited {listed.returncode}")
    real_root = root.resolve()
    directories = {parent for name in os.fsdecode(listed.stdout).split("\0") if name
                   for parent in (root / name).parents if parent != root and parent.is_relative_to(root)}
    removed = 0
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        try:
            if directory.resolve() == real_root / directory.relative_to(root):
                directory.rmdir()
                removed += 1
        except OSError:
            pass
    return removed


def _sweep_stale_bytecode_if_checkout_changed() -> None:
    """Clear ``__pycache__`` at launch when the checkout fingerprint changed since the last sweep.

    Update-time clears can't close the stale-bytecode class: ``hermes update`` runs
    the PRE-pull updater code and manual pulls never run it. Cheap file reads, no
    git subprocess. Never raises.

    The stale-bytecode bug class (issues #6207, #60242; Dhruv's WhatsApp ``cannot import name
    'parse_model_flags_detailed'`` report) has one shared shape: the checkout's ``.py`` files change (git
    pull inside ``hermes update``, a manual ``git pull``, a ZIP update, a file-sync restore) while
    ``__pycache__`` retains bytecode from the previous revision, and a later process trusts the stale
    ``.pyc`` instead of the fresh source.
    """
    from hermes_cli.main import PROJECT_ROOT, _clear_bytecode_cache, _read_git_revision_fingerprint
    try:
        fingerprint = _read_git_revision_fingerprint(PROJECT_ROOT)
        if not fingerprint:
            return  # non-git install — the ZIP update path clears explicitly
        recorded = _recorded_bytecode_fingerprint(PROJECT_ROOT)
        if recorded == fingerprint:
            return
        removed = _clear_bytecode_cache(PROJECT_ROOT)
        if removed:
            logger.info(
                "Checkout changed since last launch (%s -> %s): cleared %d stale __pycache__ director%s",
                recorded or "unknown", fingerprint, removed, "y" if removed == 1 else "ies",
            )
        if pruned := _prune_dropped_directories(PROJECT_ROOT, recorded):
            logger.info("Removed %d director%s the checkout no longer has", pruned, "y" if pruned == 1 else "ies")
        _record_bytecode_fingerprint()
    except Exception as exc:
        logger.debug("Stale-bytecode launch sweep failed: %s", exc)


