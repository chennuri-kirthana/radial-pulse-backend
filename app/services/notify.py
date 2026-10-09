"""The ONE way to send an in-app notification.

Decision (9 Oct): in-app notifications are always created. v15 has no way for the app to read
another person's switches (``notification_preferences`` is "own rows only"), and email is not
built yet (open question Q7). When email arrives, the email sender checks the switches.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.enums import NotificationCategory
from app.models import Notification


def send(
    session: Session,
    *,
    user_id: UUID,
    category: NotificationCategory,
    title: str,
    clinic_id: UUID | None = None,
    link: str | None = None,
    body: str | None = None,
) -> Notification:
    """Add the notification to the current transaction."""
    note = Notification(
        user_id=user_id, clinic_id=clinic_id, category=str(category), title=title[:200], body=body, link=link
    )
    session.add(note)
    return note
