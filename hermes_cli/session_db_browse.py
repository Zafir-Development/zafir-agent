"""Opening a profile's session store read-only for a browsing client.

The native session listener (TUI/Desktop over ``/api/ws``) reads another profile's ``state.db``
without owning it: browsing must never initialize, migrate or repair that store — only the
profile's gateway owner does. A store that lags the declared schema but has no owner is reconciled
once, in additive form; an owned or corrupt store is refused by name.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

_log = logging.getLogger(__name__)


class SessionStoreError(RuntimeError):
    """A session store that cannot be browsed. ``detail`` is the user-facing payload.

    Mirrors the HTTP detail the dashboard's session routes returned (a string, or the structured
    corrupt-store dict) so the caller can render or log the same message.
    """

    def __init__(self, detail) -> None:
        super().__init__(detail)
        self.detail = detail


# Corrupt-store reporting for polled read endpoints: a persistently malformed state.db once
# produced ~520K identical tracebacks in 24h. One WARNING per store per interval, then debug; the
# caller gets an explicit payload instead of a bare exception. The file is never quarantined or
# renamed from here — that is `hermes doctor`'s job.
_CORRUPT_STORE_WARN_INTERVAL_S = 300.0
_corrupt_store_warned_at: dict[str, float] = {}  # {db path: monotonic}

_CORRUPT_STORE_DETAIL = {
    "error": "state_db_corrupt",
    "message": "state.db corrupt — run `hermes doctor` (then `hermes doctor --fix` or `hermes sessions repair`).",
}
# One payload per persistence-cause bucket (``classify_persistence_error``); ``error`` codes
# all follow the ``state_db_*`` scheme of the pre-existing ``state_db_corrupt``.
# Same guidance as the deleted_wal / replaced turn explainers: `doctor --fix` while a holder
# lives would repair the wrong generation in place, so it is deliberately NOT suggested here.
_DELETED_WAL_DETAIL = {
    "error": "state_db_deleted_wal",
    "message": "another Hermes process still holds an old copy of the session database's write-ahead log — "
               "quit every Hermes process on this profile, run `hermes doctor` (it names the holders), "
               "then start Hermes again. Do not run `hermes doctor --fix` while they run.",
}
_STATE_DB_REPLACED_DETAIL = {
    "error": "state_db_replaced",
    "message": "state.db was replaced while Hermes was running — stop Hermes, run `hermes doctor`, "
               "then start it again. Do not run `hermes doctor --fix`, which would repair the wrong file in place.",
}
# Every other bucket a malformed image can classify as ("corrupt", "fts_index") is the corrupt payload.
_STORE_STATUS_DETAIL_BY_CAUSE = {
    "deleted_wal": _DELETED_WAL_DETAIL, "replaced": _STATE_DB_REPLACED_DETAIL}


def _corrupt_store_error(db_path: Path, exc: BaseException) -> SessionStoreError:
    """The structured corrupt-store payload, warning once per store per interval."""
    from hermes_state_errors import classify_persistence_error
    key, now = str(db_path), time.monotonic()
    last = _corrupt_store_warned_at.get(key)
    detail = _STORE_STATUS_DETAIL_BY_CAUSE.get(classify_persistence_error(exc), _CORRUPT_STORE_DETAIL)
    if last is None or now - last >= _CORRUPT_STORE_WARN_INTERVAL_S:
        _corrupt_store_warned_at[key] = now
        _log.warning("state.db at %s is unreadable (%s); reads return a status payload until it is "
                     "repaired — run `hermes doctor`", db_path, exc)
    else:
        _log.debug("state.db at %s still has error: %s", db_path, exc)
    return SessionStoreError({**detail, "path": key})


def _session_db_read_probe_statements() -> tuple:
    """Probe the declared schema without reconciling it on a browsing request."""
    from hermes_state_schema import schema_read_probe_statements

    return schema_read_probe_statements()


def open_session_db_at_path(db_path: Path, *, read_only: bool):
    """Browsing never initializes or repairs the owner's session store.

    Owner startup reconciles schema. The one write a browse may do: a store that lags
    SCHEMA_SQL (missing table/column, not corruption) with NO gateway owning it gets the
    missing declared tables/columns once, in one short locked transaction; an
    owned store is refused by name instead. Explicit mutation APIs retain their writable
    acquisition until their separate owner-RPC migration.
    """
    import sqlite3

    from hermes_state import SessionDB
    from hermes_state_errors import is_transient_sqlite_error
    from hermes_state_registry import acquire

    if not read_only:
        return acquire(db_path)

    try:
        initialized = db_path.stat().st_size > 0
    except FileNotFoundError:
        initialized = False
    if not initialized:
        raise SessionStoreError(
            "Session store is not initialized. Start this profile's gateway to initialize it.")

    from hermes_state_reconcile import (
        DeclarativeDriftError, is_declarative_drift_error, reconcile_drift_for_browse,
    )

    def _open_probed():
        db = SessionDB(db_path=db_path, read_only=True)
        try:
            conn = getattr(db, "_conn", None)
            if conn is not None:
                for statement in _session_db_read_probe_statements():
                    conn.execute(statement).fetchone()
            return db
        except BaseException:
            db.close()
            raise

    try:
        try:
            return _open_probed()
        except sqlite3.OperationalError as exc:
            # A missing declared table/column is upgrade drift, not corruption: catch an unowned
            # store up once under its runtime lock, refuse by name when a gateway owns it. Never
            # destructive: additive DDL only, no repair from browse.
            if not is_declarative_drift_error(exc):
                raise
            try:
                reconcile_drift_for_browse(db_path)
            except DeclarativeDriftError as drift:
                _log.warning("session store at %s is behind SCHEMA_SQL: %s", db_path, drift)
                raise SessionStoreError(str(drift)) from exc
            return _open_probed()
    except (sqlite3.DatabaseError, UnicodeDecodeError) as exc:
        from hermes_state_errors import is_malformed_db_error
        if isinstance(exc, sqlite3.DatabaseError) and is_malformed_db_error(exc):
            # A corrupt image names the repair (`hermes doctor`), never a generic
            # "schema unavailable".
            raise _corrupt_store_error(db_path, exc) from exc
        if isinstance(exc, sqlite3.OperationalError) and is_transient_sqlite_error(exc):
            detail = "Session store is busy (disk I/O or lock). Retry; the list was not cleared."
        else:
            detail = (
                "Session store schema is unavailable or corrupt. Start or restart this profile's "
                "gateway to reconcile it; if it persists, run `hermes doctor` for diagnosis. "
                "Browsing does not repair the store.")
        raise SessionStoreError(detail) from exc
