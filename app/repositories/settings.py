from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text

from app.core.enums import NotificationCategory, NotificationChannel
from app.models import NotificationPreference, PlatformSettings
from app.repositories.base import Repository


class SettingsRepository(Repository):
    # ------------------------------------------------------------ platform settings
    def platform(self) -> PlatformSettings | None:
        return self.session.get(PlatformSettings, 1)

    # ------------------------------------------------------------ notification switches
    def preferences_for(self, user_id: UUID) -> list[NotificationPreference]:
        return list(
            self.session.scalars(
                select(NotificationPreference).where(NotificationPreference.user_id == user_id)
            )
        )

    def preference(
        self, user_id: UUID, category: NotificationCategory, channel: NotificationChannel
    ) -> NotificationPreference | None:
        return self.session.scalar(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.category == category,
                NotificationPreference.channel == channel,
            )
        )

    def notification_enabled(
        self, user_id: UUID, category: NotificationCategory, channel: NotificationChannel
    ) -> bool:
        """Is this switch on for SOMEONE (usually not the caller)? Default: on.

        On PostgreSQL the preferences table only shows your OWN rows (row-level security), so this
        asks a SECURITY DEFINER function that answers only true/false (migration 0010).
        """
        if self.session.get_bind().dialect.name == "postgresql":
            return bool(
                self.session.scalar(
                    text("SELECT rp_notification_enabled(:u, :c, :ch)"),
                    {"u": user_id, "c": category.value, "ch": channel.value},
                )
            )
        row = self.preference(user_id, category, channel)
        return True if row is None else row.enabled
