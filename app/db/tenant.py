"""Who is asking: told to PostgreSQL at the start of EVERY transaction (CLAUDE.md rule 5).

The database's access rules (row-level security, db/schema-v15.sql section 12) read two settings:
``rp.user_id`` (the signed-in person) and ``rp.actor`` (``'system'`` for trusted jobs). They only
apply when the session runs as role ``radial_app`` (the table owner skips every rule), so each
transaction starts with:

    SET LOCAL ROLE radial_app;
    SELECT set_config('rp.user_id', '<users.id>', true);    -- or rp.actor = 'system'

Other teams' backends (``/api/v1/internal``) run as the read-only role ``radial_service``.

Only ``SET LOCAL`` / ``set_config(..., true)``: both end with the transaction, so a pooled
connection never keeps one request's identity for the next request.

How: the actor is stored on the SQLAlchemy Session (``session.info``). An ``after_begin`` hook
applies it whenever a transaction starts; changing the actor mid-transaction applies it at once.
Before sign-in is resolved the actor is ANONYMOUS: role radial_app with no user, which sees
nothing (fail closed) but may call ``rp_user_for_login``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Connection, event, text
from sqlalchemy.orm import Session, SessionTransaction

_INFO_KEY = "rp_actor"


class ActorKind(StrEnum):
    ANONYMOUS = "anonymous"  # no one yet (login lookup only)
    USER = "user"  # a signed-in person
    SYSTEM = "system"  # trusted background work and operator commands
    SERVICE = "service"  # other teams' backends, read only


@dataclass(frozen=True)
class DbActor:
    kind: ActorKind
    user_id: UUID | None = None


ANONYMOUS = DbActor(ActorKind.ANONYMOUS)
SYSTEM = DbActor(ActorKind.SYSTEM)
SERVICE = DbActor(ActorKind.SERVICE)

_APP_ROLE = text("SET LOCAL ROLE radial_app")
_SERVICE_ROLE = text("SET LOCAL ROLE radial_service")
_SETTINGS = text("SELECT set_config('rp.user_id', :user_id, true), set_config('rp.actor', :actor, true)")


def get_actor(session: Session) -> DbActor:
    actor = session.info.get(_INFO_KEY)
    return actor if isinstance(actor, DbActor) else ANONYMOUS


def _apply(connection: Connection, actor: DbActor) -> None:
    if actor.kind is ActorKind.SERVICE:
        connection.execute(_SERVICE_ROLE)
        connection.execute(_SETTINGS, {"user_id": "", "actor": ""})
        return
    connection.execute(_APP_ROLE)
    connection.execute(
        _SETTINGS,
        {
            "user_id": str(actor.user_id) if actor.kind is ActorKind.USER else "",
            "actor": "system" if actor.kind is ActorKind.SYSTEM else "",
        },
    )


def set_actor(session: Session, actor: DbActor) -> None:
    """Act as ``actor`` from now on (applied at once if a transaction is open)."""
    session.info[_INFO_KEY] = actor
    if session.in_transaction():
        _apply(session.connection(), actor)


def act_as_user(session: Session, user_id: UUID) -> None:
    set_actor(session, DbActor(ActorKind.USER, user_id))


def act_as_system(session: Session) -> None:
    set_actor(session, SYSTEM)


def act_as_service(session: Session) -> None:
    set_actor(session, SERVICE)


#: Set ``session.info[OWNER_SESSION] = True`` to skip all of this. ONLY for test set-up code that
#: logs in as the table owner to arrange data; the app never sets it.
OWNER_SESSION = "rp_owner"


@event.listens_for(Session, "after_begin")
def _apply_on_begin(session: Session, transaction: SessionTransaction, connection: Connection) -> None:
    if session.info.get(OWNER_SESSION):
        return
    _apply(connection, get_actor(session))
