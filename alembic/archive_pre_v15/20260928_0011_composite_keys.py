"""composite keys: same-clinic links and two missing natural keys

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-28

In plain words (docs/architecture/database-relationships.md):

Every table already has a primary key (``id``). What was missing:

1. **Same-clinic links.** Some rows store a ``clinic_id`` AND point at a parent row (a finding
   points at its assessment, a chat message at its file, ΓÇª). Nothing forced the parent to be in
   the SAME clinic. Now these links are composite foreign keys on two columns, e.g.
   ``assessment_findings (assessment_id, clinic_id) ΓåÆ assessments (id, clinic_id)``, so the
   database refuses a link across clinics. The parents get a matching unique key ``(id, clinic_id)``.

   | Child (columns) | Parent (columns) | On delete |
   |---|---|---|
   | assessment_components (assessment_id, clinic_id) | assessments (id, clinic_id) | cascade |
   | assessment_findings (assessment_id, clinic_id) | assessments (id, clinic_id) | cascade |
   | assessment_findings (component_id, assessment_id) | assessment_components (id, assessment_id) | cascade |
   | report_artifacts (assessment_id, clinic_id) | assessments (id, clinic_id) | refuse |
   | report_artifacts (asset_id, clinic_id) | assets (id, clinic_id) | refuse |
   | chat_messages (attachment_asset_id, clinic_id) | assets (id, clinic_id) | refuse |
   | clinics (cover_asset_id, id) | assets (id, clinic_id) | refuse |
   | assets (previous_version_id, clinic_id) | assets (id, clinic_id) | refuse |
   | work_items (approval_id, clinic_id) | approvals (id, clinic_id) | refuse |

   "Refuse" replaces the old "set to empty": the platform never hard-deletes these parents
   (it deactivates instead), so a delete that would break a link is a bug and is stopped.
   ``work_items.source_finding_id`` keeps "set to empty": findings ARE replaced when an engine
   re-runs, and the work item keeps its ``finding_code``.

2. **Natural keys.**
   * ``assessment_findings (component_id, code)``: one finding per problem code per section.
     Existing duplicates are removed (the oldest copy is kept).
   * ``practitioners (organization_id, registration_number)`` when the number is known: one
     record per doctor per business. Existing duplicates must be merged by hand first ΓÇö the
     migration stops and lists them.

Existing rows that break a same-clinic link also stop the migration with a clear message.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (name, child table, child columns, parent table, parent columns, on delete)
LINKS = [
    ("fk_assessment_components_assessment_id_assessments", "assessment_components",
     ["assessment_id", "clinic_id"], "assessments", ["id", "clinic_id"], "CASCADE"),
    ("fk_assessment_findings_assessment_id_assessments", "assessment_findings",
     ["assessment_id", "clinic_id"], "assessments", ["id", "clinic_id"], "CASCADE"),
    ("fk_assessment_findings_component_id_assessment_components", "assessment_findings",
     ["component_id", "assessment_id"], "assessment_components", ["id", "assessment_id"], "CASCADE"),
    ("fk_report_artifacts_assessment_id_assessments", "report_artifacts",
     ["assessment_id", "clinic_id"], "assessments", ["id", "clinic_id"], None),
    ("fk_report_artifacts_asset_id_assets", "report_artifacts",
     ["asset_id", "clinic_id"], "assets", ["id", "clinic_id"], None),
    ("fk_chat_messages_attachment_asset_id_assets", "chat_messages",
     ["attachment_asset_id", "clinic_id"], "assets", ["id", "clinic_id"], "RESTRICT"),
    ("fk_clinics_cover_asset_id_assets", "clinics",
     ["cover_asset_id", "id"], "assets", ["id", "clinic_id"], None),
    ("fk_assets_previous_version_id_assets", "assets",
     ["previous_version_id", "clinic_id"], "assets", ["id", "clinic_id"], None),
    ("fk_work_items_approval_id_approvals", "work_items",
     ["approval_id", "clinic_id"], "approvals", ["id", "clinic_id"], None),
]  # fmt: skip

#: The one-column links they replace, restored by the downgrade: (name, table, column, parent, on delete)
OLD_LINKS = [
    ("fk_assessment_components_assessment_id_assessments", "assessment_components", "assessment_id",
     "assessments", "CASCADE"),
    ("fk_assessment_findings_assessment_id_assessments", "assessment_findings", "assessment_id",
     "assessments", "CASCADE"),
    ("fk_assessment_findings_component_id_assessment_components", "assessment_findings", "component_id",
     "assessment_components", "CASCADE"),
    ("fk_report_artifacts_assessment_id_assessments", "report_artifacts", "assessment_id",
     "assessments", "SET NULL"),
    ("fk_report_artifacts_asset_id_assets", "report_artifacts", "asset_id", "assets", "SET NULL"),
    ("fk_chat_messages_attachment_asset_id_assets", "chat_messages", "attachment_asset_id",
     "assets", "RESTRICT"),
    ("fk_clinics_cover_asset_id_assets", "clinics", "cover_asset_id", "assets", "SET NULL"),
    ("fk_assets_previous_version_id_assets", "assets", "previous_version_id", "assets", "SET NULL"),
    ("fk_work_items_approval_id_approvals", "work_items", "approval_id", "approvals", "SET NULL"),
]  # fmt: skip

#: Parents: the extra unique key the composite links point at.
PARENT_KEYS = [
    ("uq_assessments_id_clinic_id", "assessments", ["id", "clinic_id"]),
    ("uq_assessment_components_id_assessment_id", "assessment_components", ["id", "assessment_id"]),
    ("uq_assets_id_clinic_id", "assets", ["id", "clinic_id"]),
    ("uq_approvals_id_clinic_id", "approvals", ["id", "clinic_id"]),
]


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _mismatches(child: str, cols: list[str], parent: str, pcols: list[str]) -> int:
    """Rows whose link points at a parent that does not have the same second column (e.g. clinic)."""
    join = " AND ".join(f"p.{pc} = c.{cc}" for cc, pc in zip(cols, pcols, strict=True))
    sql = (
        f"SELECT count(*) FROM {child} c WHERE c.{cols[0]} IS NOT NULL "
        f"AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE {join})"
    )
    return int(op.get_bind().execute(sa.text(sql)).scalar() or 0)


def _check_existing_data() -> None:
    problems = []
    for name, child, cols, parent, pcols, _ in LINKS:
        n = _mismatches(child, cols, parent, pcols)
        if n:
            problems.append(f"{n} row(s) in {child} break {name} ({', '.join(cols)} ΓåÆ {parent})")
    dupes = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT organization_id, registration_number, count(*) FROM practitioners "
                "WHERE registration_number IS NOT NULL "
                "GROUP BY organization_id, registration_number HAVING count(*) > 1"
            )
        )
        .all()
    )
    for org, number, n in dupes:
        problems.append(
            f"{n} practitioners in organization {org} share registration number {number} ΓÇö merge them"
        )
    if problems:
        raise RuntimeError("Migration 0011 stopped; fix these rows first:\n  " + "\n  ".join(problems))


def upgrade() -> None:
    if _is_postgres():
        _check_existing_data()
        # One finding per code per section: keep the oldest copy of any duplicate.
        op.execute(
            """
            DELETE FROM assessment_findings f USING assessment_findings keep
            WHERE f.component_id = keep.component_id AND f.code = keep.code
              AND (keep.created_at, keep.id) < (f.created_at, f.id)
            """
        )

    for name, table, cols in PARENT_KEYS:
        op.create_unique_constraint(name, table, cols)

    for name, child, cols, parent, pcols, ondelete in LINKS:
        op.drop_constraint(name, child, type_="foreignkey")
        op.create_foreign_key(name, child, parent, cols, pcols, ondelete=ondelete)

    op.create_unique_constraint(
        "uq_assessment_findings_component_id_code", "assessment_findings", ["component_id", "code"]
    )
    op.create_index(
        "uq_practitioners_organization_registration",
        "practitioners",
        ["organization_id", "registration_number"],
        unique=True,
        postgresql_where=sa.text("registration_number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_practitioners_organization_registration", table_name="practitioners")
    op.drop_constraint("uq_assessment_findings_component_id_code", "assessment_findings", type_="unique")
    for name, table, column, parent, ondelete in OLD_LINKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, parent, [column], ["id"], ondelete=ondelete)
    for name, table, _ in reversed(PARENT_KEYS):
        op.drop_constraint(name, table, type_="unique")
