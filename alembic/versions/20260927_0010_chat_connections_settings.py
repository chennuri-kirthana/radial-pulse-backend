"""chat, connected accounts and settings

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-27

In plain words (docs/architecture/chat-connections-settings.md):

1. Chat (Client Collaboration). ``chat_messages``: one conversation per clinic, never edited or
   deleted (the app login may only read and add). ``chat_read_states``: how far each person has
   read, for the unread counts. New asset kind ``chat_attachment``.
2. Connected accounts. ``platform_connections``: one row per clinic + platform (Instagram,
   Google Business Profile, ...). Tokens are NOT here — only a pointer to AWS Secrets Manager.
3. Settings. ``platform_settings`` (exactly one row: organization name, support email, timezone,
   date format); ``notification_preferences`` (a person's on/off switches); ``users.avatar_key``
   (profile photo). ``rp_notification_enabled()`` lets the app check SOMEONE ELSE's switch when it
   sends them a notification, returning only true/false.

Row-level security: clinic tables follow the clinic rule; read states and notification switches
are visible only to their owner; platform settings are readable by everyone signed in and
changeable only with the all-clinics scope (Platform Administrator).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "radial_app"
IN_SCOPE = "(rp_all_clinics() OR clinic_id = ANY (rp_clinic_ids()))"
MINE = "(user_id = rp_user_id())"  # strictly your own — not even the all-clinics scope

ASSET_KINDS = [
    "clinic_photo",
    "practitioner_photo",
    "brand_asset",
    "logo",
    "audio",
    "video",
    "report",
    "generated_media",
    "document",
]
PLATFORMS = ["google_business_profile", "instagram", "facebook", "youtube", "linkedin", "x"]
CONNECTION_STATUSES = ["not_connected", "pending", "connected", "needs_reconnect", "disconnected"]
CATEGORIES = ["clinic_assigned", "work_item_assigned", "approval_handoff"]
CHANNELS = ["in_app", "email"]
DATE_FORMATS = ["DD MMM YYYY", "DD/MM/YYYY", "YYYY-MM-DD"]


def _in(column: str, values: list[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _json() -> sa.types.TypeEngine[object]:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _asset_kind_check(kinds: list[str]) -> None:
    op.drop_constraint(op.f("ck_assets_assetkind"), "assets", type_="check")
    op.create_check_constraint(op.f("ck_assets_assetkind"), "assets", _in("kind", kinds))


def upgrade() -> None:
    # ---- users: profile photo -----------------------------------------------------------
    op.add_column("users", sa.Column("avatar_key", sa.String(length=512), nullable=True))
    _asset_kind_check([*ASSET_KINDS, "chat_attachment"])

    # ---- 1. chat -------------------------------------------------------------------------
    op.create_table(
        "chat_messages",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("sender_user_id", sa.Uuid(), nullable=True),
        sa.Column("sender_name", sa.String(length=200), nullable=False),
        sa.Column("sender_side", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("attachment_asset_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(_in("sender_side", ["radial_pulse", "clinic"]), name=op.f("ck_chat_messages_chatside")),
        sa.CheckConstraint(
            "body IS NOT NULL OR attachment_asset_id IS NOT NULL", name=op.f("ck_chat_messages_body_or_attachment")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], name=op.f("fk_chat_messages_clinic_id_clinics"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sender_user_id"], ["users.id"], name=op.f("fk_chat_messages_sender_user_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["attachment_asset_id"], ["assets.id"], name=op.f("fk_chat_messages_attachment_asset_id_assets"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
    )  # fmt: skip
    op.create_index("ix_chat_messages_clinic_time", "chat_messages", ["clinic_id", "created_at", "id"])

    op.create_table(
        "chat_read_states",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], name=op.f("fk_chat_read_states_clinic_id_clinics"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_chat_read_states_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_read_states")),
        sa.UniqueConstraint("clinic_id", "user_id", name=op.f("uq_chat_read_states_clinic_id_user_id")),
    )  # fmt: skip
    op.create_index(op.f("ix_chat_read_states_user_id"), "chat_read_states", ["user_id"])

    # ---- 2. connected accounts --------------------------------------------------------------
    op.create_table(
        "platform_connections",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
        sa.Column("external_account_name", sa.String(length=255), nullable=True),
        sa.Column("scopes", _json(), nullable=False),
        sa.Column("secret_ref", sa.String(length=512), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("oauth_state_hash", sa.String(length=64), nullable=True),
        sa.Column("oauth_code_verifier", sa.String(length=128), nullable=True),
        sa.Column("oauth_redirect_uri", sa.String(length=500), nullable=True),
        sa.Column("oauth_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("oauth_started_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("details", _json(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(_in("platform", PLATFORMS), name=op.f("ck_platform_connections_connectionplatform")),
        sa.CheckConstraint(
            _in("status", CONNECTION_STATUSES), name=op.f("ck_platform_connections_connectionstatus")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], name=op.f("fk_platform_connections_clinic_id_clinics"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connected_by_user_id"], ["users.id"],
            name=op.f("fk_platform_connections_connected_by_user_id_users"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["oauth_started_by_user_id"], ["users.id"],
            name=op.f("fk_platform_connections_oauth_started_by_user_id_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_connections")),
        sa.UniqueConstraint("clinic_id", "platform", name=op.f("uq_platform_connections_clinic_id_platform")),
    )  # fmt: skip
    op.create_index(op.f("ix_platform_connections_clinic_id"), "platform_connections", ["clinic_id"])

    # ---- 3. settings ------------------------------------------------------------------------
    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("organization_name", sa.String(length=200), nullable=False),
        sa.Column("support_email", sa.String(length=320), nullable=True),
        sa.Column("support_phone", sa.String(length=32), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("date_format", sa.String(length=16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_platform_settings_single_row")),
        sa.CheckConstraint(_in("date_format", DATE_FORMATS), name=op.f("ck_platform_settings_dateformat")),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], name=op.f("fk_platform_settings_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_settings")),
    )  # fmt: skip
    op.execute(
        "INSERT INTO platform_settings (id, organization_name, timezone, date_format) "
        "VALUES (1, 'Radial Pulse', 'Asia/Kolkata', 'DD MMM YYYY')"
    )

    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            _in("category", CATEGORIES), name=op.f("ck_notification_preferences_notificationcategory")
        ),
        sa.CheckConstraint(_in("channel", CHANNELS), name=op.f("ck_notification_preferences_notificationchannel")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_notification_preferences_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_preferences")),
        sa.UniqueConstraint(
            "user_id", "category", "channel", name=op.f("uq_notification_preferences_user_id_category_channel")
        ),
    )  # fmt: skip
    op.create_index(op.f("ix_notification_preferences_user_id"), "notification_preferences", ["user_id"])

    if not _is_postgres():
        return

    # ---- row-level security ---------------------------------------------------------------
    for table in (
        "chat_messages",
        "chat_read_states",
        "platform_connections",
        "platform_settings",
        "notification_preferences",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    # chat_messages: read + add only, inside the clinic scope. Never changed or deleted.
    op.execute(f"CREATE POLICY chat_messages_read ON chat_messages FOR SELECT TO {APP_ROLE} USING {IN_SCOPE}")
    op.execute(
        f"CREATE POLICY chat_messages_insert ON chat_messages FOR INSERT TO {APP_ROLE} WITH CHECK {IN_SCOPE}"
    )
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON chat_messages FROM {APP_ROLE}")

    # chat_read_states: your own, inside the clinic scope.
    op.execute(
        f"CREATE POLICY own_read_state ON chat_read_states TO {APP_ROLE} "
        f"USING ({IN_SCOPE} AND {MINE}) WITH CHECK ({IN_SCOPE} AND {MINE})"
    )
    op.execute(f"REVOKE DELETE, TRUNCATE ON chat_read_states FROM {APP_ROLE}")

    # platform_connections: the clinic rule (like every clinic table). No deletes (soft only).
    op.execute(
        f"CREATE POLICY tenant_isolation ON platform_connections TO {APP_ROLE} "
        f"USING {IN_SCOPE} WITH CHECK {IN_SCOPE}"
    )
    op.execute(f"REVOKE DELETE, TRUNCATE ON platform_connections FROM {APP_ROLE}")

    # platform_settings: everyone signed in reads; only the all-clinics scope changes it.
    op.execute(f"CREATE POLICY settings_read ON platform_settings FOR SELECT TO {APP_ROLE} USING (true)")
    op.execute(
        f"CREATE POLICY settings_update ON platform_settings FOR UPDATE TO {APP_ROLE} "
        "USING (rp_all_clinics()) WITH CHECK (rp_all_clinics())"
    )
    op.execute(f"REVOKE INSERT, DELETE, TRUNCATE ON platform_settings FROM {APP_ROLE}")

    # notification_preferences: only your own switches.
    op.execute(
        f"CREATE POLICY own_preferences ON notification_preferences TO {APP_ROLE} USING {MINE} WITH CHECK {MINE}"
    )

    # Sending someone a notification needs to know if they switched it off — and nothing else.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION rp_notification_enabled(p_user uuid, p_category text, p_channel text)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
          SELECT coalesce(
            (SELECT enabled FROM notification_preferences
             WHERE user_id = p_user AND category = p_category AND channel = p_channel),
            true)
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION rp_notification_enabled(uuid, text, text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION rp_notification_enabled(uuid, text, text) TO {APP_ROLE}")


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP FUNCTION IF EXISTS rp_notification_enabled(uuid, text, text)")
    op.drop_index(op.f("ix_notification_preferences_user_id"), table_name="notification_preferences")
    op.drop_table("notification_preferences")
    op.drop_table("platform_settings")
    op.drop_index(op.f("ix_platform_connections_clinic_id"), table_name="platform_connections")
    op.drop_table("platform_connections")
    op.drop_index(op.f("ix_chat_read_states_user_id"), table_name="chat_read_states")
    op.drop_table("chat_read_states")
    op.drop_index("ix_chat_messages_clinic_time", table_name="chat_messages")
    op.drop_table("chat_messages")
    # Chat attachments become plain documents before the kind disappears.
    op.execute("UPDATE assets SET kind = 'document' WHERE kind = 'chat_attachment'")
    _asset_kind_check(ASSET_KINDS)
    op.drop_column("users", "avatar_key")
