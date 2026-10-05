"""new names: doctors -> practitioners

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26

Terminology decision (Project_Entity_Terminology_Mapping): Doctor -> Practitioner, everywhere.

    table doctors                      -> practitioners   (rows, RLS policy and grants move with it)
    its PK / FKs / index names         -> renamed to match the new table name
    assets.kind 'doctor_photo'         -> 'practitioner_photo'   (data + CHECK rule)

`clinic_id` is NOT renamed: row-level security keys on it in every clinic table.
Downgrade restores the old names.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ASSET_KINDS_BASE = [
    "clinic_photo",
    "brand_asset",
    "logo",
    "audio",
    "video",
    "report",
    "generated_media",
    "document",
]

_RENAMES = [  # (kind, old, new)
    ("constraint", "pk_doctors", "pk_practitioners"),
    ("constraint", "fk_doctors_clinic_id_clinics", "fk_practitioners_clinic_id_clinics"),
    ("constraint", "fk_doctors_user_id_users", "fk_practitioners_user_id_users"),
    ("index", "ix_doctors_clinic_id", "ix_practitioners_clinic_id"),
]


def _asset_kind_check(photo_kind: str) -> None:
    kinds = [_ASSET_KINDS_BASE[0], photo_kind, *_ASSET_KINDS_BASE[1:]]
    allowed = ", ".join(f"'{k}'" for k in kinds)
    op.create_check_constraint(op.f("ck_assets_assetkind"), "assets", f"kind IN ({allowed})")


def _rename_objects(table: str, forward: bool) -> None:
    for kind, old, new in _RENAMES:
        src, dst = (old, new) if forward else (new, old)
        if kind == "index":
            op.execute(f"ALTER INDEX {src} RENAME TO {dst}")
        else:
            op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {src} TO {dst}")


def upgrade() -> None:
    op.rename_table("doctors", "practitioners")
    _rename_objects("practitioners", forward=True)

    op.drop_constraint(op.f("ck_assets_assetkind"), "assets", type_="check")
    op.execute("UPDATE assets SET kind = 'practitioner_photo' WHERE kind = 'doctor_photo'")
    _asset_kind_check("practitioner_photo")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_assets_assetkind"), "assets", type_="check")
    op.execute("UPDATE assets SET kind = 'doctor_photo' WHERE kind = 'practitioner_photo'")
    _asset_kind_check("doctor_photo")

    _rename_objects("practitioners", forward=False)
    op.rename_table("practitioners", "doctors")
