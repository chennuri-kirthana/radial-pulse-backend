"""The ONE way to send an in-app notification.

It respects the person's switches (Settings → Notifications).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.enums import NotificationCategory, NotificationChannel
from app.models import Notification
from app.repositories.settings import SettingsRepository


def send(
    session: Session,
    *,
    user_id: UUID,
    category: NotificationCategory,
    kind: str,
    title: str,
    clinic_id: UUID | None = None,
    link: str | None = None,
    body: str | None = None,
) -> Notification | None:
    """Add the notification to the current transaction, unless the person switched this category off."""
    if not SettingsRepository(session).notification_enabled(user_id, category, NotificationChannel.IN_APP):
        return None
    note = Notification(
        user_id=user_id, clinic_id=clinic_id, kind=kind, title=title[:200], body=body, link=link
    )
    session.add(note)
    return note
