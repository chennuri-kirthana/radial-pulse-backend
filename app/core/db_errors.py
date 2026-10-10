"""Database refusal → API error, following the error table in CLAUDE.md.

The database enforces many rules itself (row-level security, CHECKs, triggers). When it says
no, we turn its SQLSTATE into the matching ``AppError`` here, in ONE place, instead of catching
``IntegrityError`` in every service.

| SQLSTATE | HTTP | code |
|---|---|---|
| 42501 insufficient_privilege (guards, row-level security) | 403 | forbidden |
| 23505 unique_violation | 409 | state_conflict (voice title: its own message) |
| 23503 foreign_key_violation | 409 | state_conflict |
| 23514 from a CHECK rule | 400 | invalid_request + fields |
| 23514 from the v15 input triggers (year in the future, unknown time zone) | 400 | invalid_request + fields |
| 23514 from the business triggers (last admin, assignee, role, threads) | 409 | state_conflict + message |
| 23502 not_null_violation | 400 | invalid_request + fields |

Messages that reach the user are either our own text or a trigger message written for people
(db/schema-v15.sql). PostgreSQL's own CHECK / unique messages are never passed on: they can
contain the failing row.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    InvalidRequestError,
    ServiceUnavailableError,
)

INSUFFICIENT_PRIVILEGE = "42501"
UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"
CHECK_VIOLATION = "23514"
NOT_NULL_VIOLATION = "23502"

VOICE_TITLE_CONSTRAINT = "uq_voice_samples_one_per_title"
VOICE_TITLE_MESSAGE = "This title is already used. Please give another title."

#: v15 input triggers: "<column> (<year>) cannot be in the future",
#: 'consultation_time_zone "<x>" is not a known time zone (e.g. Asia/Kolkata)'.
_INPUT_TRIGGER = re.compile(r"^(?P<field>[a-z_]+) .*(cannot be in the future|is not a known time zone)")


def _sqlstate(exc: BaseException) -> str | None:
    state = getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)
    return str(state) if state else None


def _diag(exc: BaseException, name: str) -> str | None:
    diag = getattr(exc, "diag", None)
    value = getattr(diag, name, None) if diag is not None else None
    return str(value) if value else None


def _check_field(constraint: str | None, table: str | None) -> str:
    """ck_<table>_<rule> → the column it guards, else <rule>.

    v15 names CHECKs after the column or the rule: ck_clinics_country_code guards ``country``,
    ck_clinics_archive_reason is a rule over two columns. We pick the longest column name of the
    table that the rule starts with.
    """
    if not (constraint and table and constraint.startswith(f"ck_{table}_")):
        return constraint or "request"
    rule = constraint[len(f"ck_{table}_") :]
    from app.db.base import Base  # late import: models are only needed when a CHECK fails

    known = Base.metadata.tables.get(table)
    columns = sorted((c.name for c in known.columns), key=len, reverse=True) if known is not None else []
    return next((c for c in columns if rule == c or rule.startswith(c + "_")), rule)


#: SQLSTATE class 08 = "connection exception"; 57P03 = "cannot connect now" (server starting up).
CONNECTION_EXCEPTION_CLASS = "08"
CANNOT_CONNECT_NOW = "57P03"
DATABASE_UNREACHABLE_MESSAGE = "The database is not reachable right now. Please try again in a moment."


def _is_connection_failure(orig: Any, state: str | None) -> bool:
    """psycopg could not reach or keep a connection: wrong network path, paused Aurora, timeout.

    psycopg reports these as ``OperationalError`` with no SQLSTATE (the server never answered) or
    one of class 08 / 57P03. Other ``OperationalError`` subclasses with a SQLSTATE (serialization
    failures, cancelled queries) are real query outcomes and stay out of this.
    """
    import psycopg  # the driver is a runtime dependency; imported here to keep this module import-light

    if not isinstance(orig, psycopg.OperationalError):
        return False
    return state is None or state.startswith(CONNECTION_EXCEPTION_CLASS) or state == CANNOT_CONNECT_NOW


def app_error_for(exc: BaseException) -> AppError | None:
    """The API error for a database exception, or None if it is not a known refusal.

    Accepts the driver exception (psycopg) or a SQLAlchemy wrapper (uses ``.orig``).
    """
    orig: Any = getattr(exc, "orig", None) or exc
    state = _sqlstate(orig)
    if _is_connection_failure(orig, state):
        # 503, not 500: the request was fine, the database could not be reached (retry later).
        return ServiceUnavailableError(DATABASE_UNREACHABLE_MESSAGE)
    if state is None:
        return None
    message = _diag(orig, "message_primary") or ""
    constraint = _diag(orig, "constraint_name")
    table = _diag(orig, "table_name")

    if state == INSUFFICIENT_PRIVILEGE:
        # Guard triggers explain who may do it. PostgreSQL's own texts ("violates row-level security
        # policy for table …", "permission denied for table …") name tables, so hide those.
        own_text = "row-level security" in message or message.startswith("permission denied")
        detail = None if own_text else message or None
        return ForbiddenError(detail)
    if state == UNIQUE_VIOLATION:
        if constraint == VOICE_TITLE_CONSTRAINT:
            return ConflictError(VOICE_TITLE_MESSAGE)
        return ConflictError("This already exists.")
    if state == FOREIGN_KEY_VIOLATION:
        return ConflictError("This refers to something that does not exist, or is still in use.")
    if state == NOT_NULL_VIOLATION:
        column = _diag(orig, "column_name") or "request"
        return InvalidRequestError("A required value is missing.", fields={column: "This value is required."})
    if state == CHECK_VIOLATION:
        if constraint:  # a CHECK rule on the table
            field = _check_field(constraint, table)
            return InvalidRequestError(
                "A value is not allowed.", fields={field: "This value is not allowed."}
            )
        match = _INPUT_TRIGGER.match(message)
        if match:  # v15 input triggers: bad input, not a state problem
            return InvalidRequestError(message, fields={match.group("field"): message})
        return ConflictError(message or None)  # business triggers: the message is written for people
    return None
