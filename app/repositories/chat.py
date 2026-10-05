from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text, tuple_

from app.models import ChatMessage, ChatReadState, Clinic
from app.repositories.base import Repository


def _aware(value: datetime) -> datetime:
    """SQLite (fast tests) gives back times without a timezone; PostgreSQL keeps it. All are UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class ThreadSummary:
    clinic_id: UUID
    clinic_name: str
    last_message: ChatMessage
    unread_count: int


class ChatRepository(Repository):
    """All chat SQL. Every method takes the clinic id(s) it may touch."""

    # ------------------------------------------------------------------ messages
    def stamp_for_new_message(self, clinic_id: UUID) -> datetime:
        """The time for a new message, safe for polling.

        Polling asks for "messages after the last one I have". That only works if a message can
        never appear later with an OLDER time. So on PostgreSQL we (1) let one sender at a time
        write into a clinic's chat (a lock held until COMMIT) and (2) take the time from the
        database clock, not from each server's own clock.
        """
        if self.session.get_bind().dialect.name != "postgresql":
            return datetime.now(UTC)
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"chat:{clinic_id}"}
        )
        return _aware(self.session.scalar(text("SELECT clock_timestamp()")))

    def newest_time(self, clinic_id: UUID) -> datetime | None:
        return self.session.scalar(
            select(func.max(ChatMessage.created_at)).where(ChatMessage.clinic_id == clinic_id)
        )

    def get_in_clinic(self, clinic_id: UUID, message_id: UUID) -> ChatMessage | None:
        return self.session.scalar(
            select(ChatMessage).where(ChatMessage.clinic_id == clinic_id, ChatMessage.id == message_id)
        )

    def page(
        self,
        clinic_id: UUID,
        *,
        before: ChatMessage | None,
        after: ChatMessage | None,
        limit: int,
    ) -> tuple[list[ChatMessage], bool]:
        """A page of messages, OLDEST FIRST, and whether more exist in the direction asked.

        * no cursor → the newest ``limit`` messages (more = older ones exist)
        * ``before`` → the ``limit`` messages just older than it (scrolling up)
        * ``after``  → the messages newer than it, up to ``limit`` (polling for new ones)
        """
        order = (ChatMessage.created_at, ChatMessage.id)
        stmt = select(ChatMessage).where(ChatMessage.clinic_id == clinic_id)
        if after is not None:
            stmt = stmt.where(tuple_(*order) > tuple_(after.created_at, after.id))
            rows = list(self.session.scalars(stmt.order_by(*order).limit(limit + 1)))
            return rows[:limit], len(rows) > limit
        if before is not None:
            stmt = stmt.where(tuple_(*order) < tuple_(before.created_at, before.id))
        rows = list(
            self.session.scalars(
                stmt.order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(limit + 1)
            )
        )
        more = len(rows) > limit
        return list(reversed(rows[:limit])), more

    # ------------------------------------------------------------------ read states
    def read_state(self, clinic_id: UUID, user_id: UUID) -> ChatReadState | None:
        return self.session.scalar(
            select(ChatReadState).where(
                ChatReadState.clinic_id == clinic_id, ChatReadState.user_id == user_id
            )
        )

    def clinics_with_read_state(self, user_id: UUID) -> set[UUID]:
        return set(
            self.session.scalars(select(ChatReadState.clinic_id).where(ChatReadState.user_id == user_id))
        )

    def unread_count(self, clinic_id: UUID, user_id: UUID) -> int:
        return self.unread_counts([clinic_id], user_id).get(clinic_id, 0)

    def unread_counts(self, clinic_ids: list[UUID], user_id: UUID) -> dict[UUID, int]:
        """Messages from OTHER people that arrived after this person last read, per clinic."""
        if not clinic_ids:
            return {}
        stmt = (
            select(ChatMessage.clinic_id, func.count())
            .outerjoin(
                ChatReadState,
                and_(ChatReadState.clinic_id == ChatMessage.clinic_id, ChatReadState.user_id == user_id),
            )
            .where(
                ChatMessage.clinic_id.in_(clinic_ids),
                or_(
                    ChatReadState.last_read_at.is_(None), ChatMessage.created_at > ChatReadState.last_read_at
                ),
                or_(ChatMessage.sender_user_id.is_(None), ChatMessage.sender_user_id != user_id),
            )
            .group_by(ChatMessage.clinic_id)
        )
        return {clinic_id: int(count) for clinic_id, count in self.session.execute(stmt)}

    # ------------------------------------------------------------------ inbox
    def threads(self, clinic_ids: list[UUID], user_id: UUID, limit: int) -> list[ThreadSummary]:
        """One line per clinic that has messages: its newest message and my unread count."""
        if not clinic_ids:
            return []
        ranked = (
            select(
                ChatMessage.id.label("message_id"),
                func.row_number()
                .over(
                    partition_by=ChatMessage.clinic_id,
                    order_by=(ChatMessage.created_at.desc(), ChatMessage.id.desc()),
                )
                .label("rn"),
            )
            .where(ChatMessage.clinic_id.in_(clinic_ids))
            .subquery()
        )
        stmt = (
            select(ChatMessage, Clinic.name)
            .join(ranked, and_(ranked.c.message_id == ChatMessage.id, ranked.c.rn == 1))
            .join(Clinic, Clinic.id == ChatMessage.clinic_id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit)
        )
        rows = list(self.session.execute(stmt))
        unread = self.unread_counts([m.clinic_id for m, _ in rows], user_id)
        return [
            ThreadSummary(
                clinic_id=m.clinic_id,
                clinic_name=name,
                last_message=m,
                unread_count=unread.get(m.clinic_id, 0),
            )
            for m, name in rows
        ]

    def mark_read(self, clinic_id: UUID, user_id: UUID, at: datetime) -> ChatReadState:
        """Move this person's "read up to" mark forward (never backwards)."""
        state = self.read_state(clinic_id, user_id)
        if state is None:
            state = ChatReadState(clinic_id=clinic_id, user_id=user_id, last_read_at=at)
            self.session.add(state)
        elif _aware(at) > _aware(state.last_read_at):
            state.last_read_at = at
        self.session.flush()
        return state
