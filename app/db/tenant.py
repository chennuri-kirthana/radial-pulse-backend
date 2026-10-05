"""Tenant context for PostgreSQL row-level security (RLS).

The application decides WHICH clinics a request may touch (app/dependencies/tenancy.py).
This module hands that decision to PostgreSQL, so the database ALSO refuses other
clinics' rows — a second net if a query ever forgets `WHERE clinic_id = …`.

How it works
------------
* The scope is stored on the SQLAlchemy Session (`session.info`).
* At the start of EVERY transaction (`after_begin`) — and immediately, if a transaction is
  already open — we run `set_config('app.clinic_ids', …, true)` and
  `set_config('app.all_clinics', …, true)`. The `true` makes them transaction-local, so a
  pooled connection never leaks one request's scope into another.
* RLS policies (migration 0003) read these settings through `rp_clinic_ids()` and
  `rp_all_clinics()`.
* No scope set → no clinic rows are visible (fail closed).
* ``app.user_id`` / ``app.is_staff`` say WHO is asking. The people tables (users, memberships,
  assignments, organizations, notifications — migration 0007) use them so a person can always
  see their own rows, and Radial Pulse staff can see each other.
* SQLite (fast unit tests) has no RLS; everything here is a no-op there.

RLS applies to the non-owner `radial_app` role the API and worker log in as. Migrations run
as the owner and are not affected.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from uuid import UUID

from sqlalchemy import Connection, event, text
from sqlalchemy.orm import Session, SessionTransaction

_INFO_KEY = "tenant_scope"
_SET_SQL = text(
    "SELECT set_config('app.all_clinics', :all_clinics, true), "
    "set_config('app.clinic_ids', :clinic_ids, true), "
    "set_config('app.user_id', :user_id, true), "
    "set_config('app.is_staff', :is_staff, true)"
)


@dataclass(frozen=True)
class TenantScope:
    all_clinics: bool
    clinic_ids: frozenset[UUID]
    #: The signed-in person (None for services, CLI and before sign-in is resolved).
    user_id: UUID | None = None
    #: Radial Pulse staff (Platform Administrator / DSM): may see other staff accounts.
    is_staff: bool = False

    def params(self) -> dict[str, str]:
        ids = "{" + ",".join(sorted(str(c) for c in self.clinic_ids)) + "}"
        return {
            "all_clinics": "on" if self.all_clinics else "off",
            "clinic_ids": ids,
            "user_id": str(self.user_id) if self.user_id else "",
            "is_staff": "on" if self.is_staff else "off",
        }


NO_ACCESS = TenantScope(all_clinics=False, clinic_ids=frozenset())


def _is_postgres(session: Session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def _apply_now(session: Session) -> None:
    if _is_postgres(session) and session.in_transaction():
        session.execute(_SET_SQL, get_tenant_scope(session).params())


def get_tenant_scope(session: Session) -> TenantScope:
    scope = session.info.get(_INFO_KEY)
    return scope if isinstance(scope, TenantScope) else NO_ACCESS


def set_tenant_scope(session: Session, clinic_ids: Iterable[UUID] | None) -> None:
    """Restrict this session to `clinic_ids`. `None` = all clinics (Platform Administrator only)."""
    current = get_tenant_scope(session)
    scope = (
        replace(current, all_clinics=True, clinic_ids=frozenset())
        if clinic_ids is None
        else replace(current, all_clinics=False, clinic_ids=frozenset(clinic_ids))
    )
    session.info[_INFO_KEY] = scope
    _apply_now(session)


def set_current_user(session: Session, user_id: UUID | None, is_staff: bool = False) -> None:
    """Tell the database WHO is asking (keeps the clinic scope as it is)."""
    session.info[_INFO_KEY] = replace(get_tenant_scope(session), user_id=user_id, is_staff=is_staff)
    _apply_now(session)


def add_clinic_to_scope(session: Session, clinic_id: UUID) -> None:
    """Widen the scope by one clinic — used right after an AUTHORIZED clinic creation."""
    scope = get_tenant_scope(session)
    if scope.all_clinics:
        return
    session.info[_INFO_KEY] = replace(scope, clinic_ids=scope.clinic_ids | {clinic_id})
    _apply_now(session)


@event.listens_for(Session, "after_begin")
def _apply_on_begin(session: Session, transaction: SessionTransaction, connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        connection.execute(_SET_SQL, get_tenant_scope(session).params())
