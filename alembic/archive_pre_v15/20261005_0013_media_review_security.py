"""clinic media review: labels, practitioner link, staff-only review, private notes, safety nets

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-05

In plain words (backend architecture audit, 5 Oct 2026):

1. **Media labels as data.** ``media_taxonomy`` holds the V1 values: 6 Hospital/Clinic photo
   categories, doctor-photo apron (2), angle (5) and outfit (2), and 1 voice sample. New values are
   new rows, never a new CHECK value. ``assets`` gets ``category_id``, ``apron_id``, ``angle_id``,
   ``outfit_id`` and ``practitioner_id`` (a doctor photo shows a practitioner of THE SAME clinic:
   composite foreign key to ``clinic_practitioners``).

2. **Internal review notes are private.** They move from ``approvals.last_comment`` (readable by
   clinic people) to the new ``approval_notes`` table, which only Radial Pulse staff can read or
   write. ``approvals.clinic_message`` is the reason the clinic may read. ``last_comment`` is emptied
   and no longer used; drop it in a later migration.

3. **Database safety nets** for the rules the API enforces. They act on the app login only (where
   row-level security applies), never on the owner login used by migrations:
   * every review decision (approve, reject, retake/redo, publish, handoff, clinic message) is
     Radial Pulse staff work; clinic people may only submit their own clinic media
     (clinic_photo, practitioner_photo, audio), and nothing is reviewed before its upload is confirmed;
   * clinic people never see the review of an assessment (staff-only), nor review activity
     (``approval.*``) and assessment work in the audit log;
   * clinic people never see report files that are not published;
   * nobody changes their OWN role or active flag, and only the all-clinics scope (Platform
     Administrator) changes anyone's role or active flag; nobody changes their own clinic role.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "radial_app"
IN_SCOPE = "(rp_all_clinics() OR clinic_id = ANY (rp_clinic_ids()))"
STAFF = "(rp_is_staff() OR rp_all_clinics())"

DIMENSIONS = [
    "clinic_photo_category",
    "voice_sample",
    "practitioner_apron",
    "practitioner_angle",
    "practitioner_outfit",
]

#: The exact V1 values (product owner, 5 Oct 2026), in display order. Frozen here: later
#: values come in later migrations.
V1_TAXONOMY: list[tuple[str, str, str]] = [
    ("clinic_photo_category", "exterior_signage", "Exterior & signage"),
    ("clinic_photo_category", "reception_waiting", "Reception & waiting"),
    ("clinic_photo_category", "consult_procedure_rooms", "Consult & procedure rooms"),
    ("clinic_photo_category", "equipment_facilities", "Equipment & facilities"),
    ("clinic_photo_category", "team_at_work", "Team at work"),
    ("clinic_photo_category", "logo_cover_photo", "Logo & cover photo"),
    ("practitioner_apron", "with_apron", "With apron"),
    ("practitioner_apron", "without_apron", "Without apron"),
    ("practitioner_angle", "90_left", "90┬░ L"),
    ("practitioner_angle", "45_left", "45┬░ L"),
    ("practitioner_angle", "straight", "0┬░"),
    ("practitioner_angle", "45_right", "45┬░ R"),
    ("practitioner_angle", "90_right", "90┬░ R"),
    ("practitioner_outfit", "outfit_1", "Outfit 1"),
    ("practitioner_outfit", "outfit_2", "Outfit 2"),
    ("voice_sample", "clinic_greeting", "Clinic greeting"),
]

MEDIA_KINDS = "('clinic_photo', 'practitioner_photo', 'audio')"
LABEL_COLUMNS = ("category_id", "apron_id", "angle_id", "outfit_id")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _in(column: str, values: list[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    # ---- 1. media labels ----------------------------------------------------------------------
    taxonomy = op.create_table(
        "media_taxonomy",
        sa.Column("dimension", sa.String(length=40), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            _in("dimension", DIMENSIONS), name=op.f("ck_media_taxonomy_mediataxonomydimension")
        ),
        sa.CheckConstraint("sort_order >= 0", name=op.f("ck_media_taxonomy_sort_order_not_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_taxonomy")),
        sa.UniqueConstraint("dimension", "code", name=op.f("uq_media_taxonomy_dimension_code")),
    )
    if _is_postgres():
        op.create_check_constraint(
            op.f("ck_media_taxonomy_code_format"), "media_taxonomy", "code ~ '^[a-z0-9_]+$'"
        )
    order: dict[str, int] = {}
    rows = []
    for dimension, code, label in V1_TAXONOMY:
        order[dimension] = order.get(dimension, -1) + 1
        rows.append(
            {"id": uuid.uuid4(), "dimension": dimension, "code": code, "label": label,
             "sort_order": order[dimension], "is_active": True}
        )  # fmt: skip
    op.bulk_insert(taxonomy, rows)

    op.add_column("assets", sa.Column("practitioner_id", sa.Uuid(), nullable=True))
    for column in LABEL_COLUMNS:
        op.add_column("assets", sa.Column(column, sa.Uuid(), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_assets_{column}_media_taxonomy"), "assets", "media_taxonomy", [column], ["id"]
        )
        op.create_index(
            f"ix_assets_{column}", "assets", [column], postgresql_where=sa.text(f"{column} IS NOT NULL")
        )
    op.create_foreign_key(
        "fk_assets_clinic_practitioner",
        "assets",
        "clinic_practitioners",
        ["clinic_id", "practitioner_id"],
        ["clinic_id", "practitioner_id"],
    )
    op.create_index(
        "ix_assets_clinic_practitioner",
        "assets",
        ["clinic_id", "practitioner_id"],
        postgresql_where=sa.text("practitioner_id IS NOT NULL"),
    )
    op.create_check_constraint(
        op.f("ck_assets_practitioner_only_on_doctor_photos"),
        "assets",
        "practitioner_id IS NULL OR kind = 'practitioner_photo'",
    )
    op.create_check_constraint(
        op.f("ck_assets_doctor_labels_only_on_doctor_photos"),
        "assets",
        "(apron_id IS NULL AND angle_id IS NULL AND outfit_id IS NULL) OR kind = 'practitioner_photo'",
    )
    op.create_check_constraint(
        op.f("ck_assets_category_only_on_clinic_photos_and_voice"),
        "assets",
        "category_id IS NULL OR kind IN ('clinic_photo', 'audio')",
    )

    # ---- 2. private review notes + the clinic-facing message -------------------------------------
    op.add_column("approvals", sa.Column("clinic_message", sa.Text(), nullable=True))
    op.create_table(
        "approval_notes",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("length(body) > 0", name=op.f("ck_approval_notes_body_not_empty")),
        sa.ForeignKeyConstraint(
            ["approval_id", "clinic_id"], ["approvals.id", "approvals.clinic_id"],
            name=op.f("fk_approval_notes_approval_id_approvals"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"], ["users.id"], name=op.f("fk_approval_notes_author_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], name=op.f("fk_approval_notes_clinic_id_clinics"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_notes")),
    )  # fmt: skip
    op.create_index("ix_approval_notes_approval_created", "approval_notes", ["approval_id", "created_at"])
    op.create_index(op.f("ix_approval_notes_clinic_id"), "approval_notes", ["clinic_id"])

    # Existing comments were written by reviewers: they become internal notes, then leave approvals.
    bind = op.get_bind()
    old = bind.execute(
        sa.text(
            "SELECT id, clinic_id, coalesce(decided_by_user_id, submitted_by_user_id), last_comment, updated_at "
            "FROM approvals WHERE last_comment IS NOT NULL AND length(last_comment) > 0"
        )
    ).all()
    notes = sa.table(
        "approval_notes",
        sa.column("id", sa.Uuid()),
        sa.column("clinic_id", sa.Uuid()),
        sa.column("approval_id", sa.Uuid()),
        sa.column("author_user_id", sa.Uuid()),
        sa.column("body", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    if old:
        op.bulk_insert(
            notes,
            [
                {"id": uuid.uuid4(), "clinic_id": clinic_id, "approval_id": approval_id,
                 "author_user_id": author, "body": body, "created_at": at}
                for approval_id, clinic_id, author, body, at in old
            ],
        )  # fmt: skip
    op.execute("UPDATE approvals SET last_comment = NULL WHERE last_comment IS NOT NULL")
    if _is_postgres():
        # The status-copy check on approvals is DEFERRED; run it now so later DDL is allowed.
        op.execute("SET CONSTRAINTS ALL IMMEDIATE")

    if not _is_postgres():
        return

    # ---- 3. row-level security -----------------------------------------------------------------
    # media_taxonomy: everyone signed in reads; values change only through migrations.
    op.execute("ALTER TABLE media_taxonomy ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY taxonomy_read ON media_taxonomy FOR SELECT TO {APP_ROLE} USING (true)")
    op.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON media_taxonomy FROM {APP_ROLE}")

    # approval_notes: Radial Pulse staff of the clinic only. Added, never changed or deleted.
    op.execute("ALTER TABLE approval_notes ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY staff_notes_read ON approval_notes FOR SELECT TO {APP_ROLE} "
        f"USING ({IN_SCOPE} AND {STAFF})"
    )
    op.execute(
        f"CREATE POLICY staff_notes_insert ON approval_notes FOR INSERT TO {APP_ROLE} "
        f"WITH CHECK ({IN_SCOPE} AND {STAFF})"
    )
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON approval_notes FROM {APP_ROLE}")

    # approvals: the review of an assessment is staff-only (decision D15). RESTRICTIVE = it is
    # added ON TOP of the clinic rule, never instead of it.
    op.execute(
        f"CREATE POLICY staff_only_reviews ON approvals AS RESTRICTIVE TO {APP_ROLE} "
        f"USING (resource_type <> 'assessment' OR {STAFF}) "
        f"WITH CHECK (resource_type <> 'assessment' OR {STAFF})"
    )

    # assets: clinic people see a report file only once its report is published. The check reads
    # report_artifacts as the owner (SECURITY DEFINER) and returns only true/false.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION rp_report_file_published(p_asset uuid, p_kind text) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
          SELECT EXISTS (SELECT 1 FROM report_artifacts r
                         WHERE r.asset_id = p_asset AND r.publication_state = 'published')
              OR (p_kind <> 'report'
                  AND NOT EXISTS (SELECT 1 FROM report_artifacts r WHERE r.asset_id = p_asset))
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION rp_report_file_published(uuid, text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION rp_report_file_published(uuid, text) TO {APP_ROLE}")
    op.execute(
        f"CREATE POLICY clinic_sees_published_report_files ON assets AS RESTRICTIVE FOR SELECT TO {APP_ROLE} "
        f"USING ({STAFF} OR rp_report_file_published(id, kind))"
    )

    # audit_events: review activity (approval.*) and assessment work stay internal (decision D25).
    op.execute(
        f"CREATE POLICY internal_review_activity ON audit_events AS RESTRICTIVE FOR SELECT TO {APP_ROLE} "
        f"USING ({STAFF} OR NOT (action LIKE 'approval.%' OR resource_type = 'assessment'))"
    )

    # ---- 4. safety-net triggers (app login only: row_security_active is false for the owner) ----
    # approvals: every review decision is Radial Pulse staff work (decision D24). The ONLY thing a
    # clinic person may do is submit their own clinic media once its upload is confirmed.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION rp_guard_approvals() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          v_kind text;
          v_status text;
          v_state_changed boolean;
          v_other_changed boolean;
        BEGIN
          IF NOT row_security_active('approvals') THEN
            RETURN NEW;
          END IF;
          IF TG_OP = 'INSERT' THEN
            v_state_changed := true;
            v_other_changed := NEW.decided_by_user_id IS NOT NULL OR NEW.clinic_message IS NOT NULL
                               OR NEW.publication_state <> 'unpublished' OR NEW.assignee_user_id IS NOT NULL;
          ELSE
            v_state_changed := NEW.state IS DISTINCT FROM OLD.state;
            v_other_changed := NEW.decided_by_user_id IS DISTINCT FROM OLD.decided_by_user_id
                               OR (NEW.clinic_message IS NOT NULL
                                   AND NEW.clinic_message IS DISTINCT FROM OLD.clinic_message)
                               OR NEW.publication_state IS DISTINCT FROM OLD.publication_state
                               OR NEW.assignee_user_id IS DISTINCT FROM OLD.assignee_user_id
                               OR NEW.resource_type IS DISTINCT FROM OLD.resource_type
                               OR NEW.resource_id IS DISTINCT FROM OLD.resource_id;
          END IF;
          IF NEW.resource_type = 'asset' THEN
            SELECT kind, status INTO v_kind, v_status
              FROM assets WHERE id = NEW.resource_id AND clinic_id = NEW.clinic_id;
            IF NOT FOUND THEN
              RAISE EXCEPTION 'asset % not found for review', NEW.resource_id
                USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF v_state_changed AND NEW.state <> 'draft' AND v_status <> 'uploaded' THEN
              RAISE EXCEPTION 'asset % cannot be reviewed before its upload is confirmed', NEW.resource_id
                USING ERRCODE = 'check_violation';
            END IF;
          END IF;
          -- A clinic person: their own media only, a new review (draft) moving to submitted, nothing else.
          -- (The app inserts the review as draft and moves it to submitted in the same transaction.)
          IF NOT {STAFF} THEN
            IF NEW.resource_type <> 'asset' OR v_kind NOT IN {MEDIA_KINDS} OR v_other_changed
               OR (v_state_changed AND NEW.state NOT IN ('draft', 'submitted'))
               OR (v_state_changed AND TG_OP = 'UPDATE' AND OLD.state <> 'draft') THEN
              RAISE EXCEPTION 'only Radial Pulse staff review: clinic people may only submit their own media'
                USING ERRCODE = 'insufficient_privilege';
            END IF;
          END IF;
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER approvals_guard BEFORE INSERT OR UPDATE ON approvals "
        "FOR EACH ROW EXECUTE FUNCTION rp_guard_approvals()"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION rp_guard_user_changes() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF row_security_active('users')
             AND (NEW.platform_role IS DISTINCT FROM OLD.platform_role
                  OR NEW.is_active IS DISTINCT FROM OLD.is_active)
             AND (NOT rp_all_clinics() OR (OLD.id = rp_user_id()) IS TRUE) THEN
            RAISE EXCEPTION 'role and active flag change only by a Platform Administrator, never on your own account'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER users_guard_changes BEFORE UPDATE ON users "
        "FOR EACH ROW EXECUTE FUNCTION rp_guard_user_changes()"
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION rp_guard_membership_changes() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT row_security_active('clinic_memberships') THEN
            RETURN NEW;
          END IF;
          IF TG_OP = 'INSERT' THEN
            IF (NEW.user_id = rp_user_id()) IS TRUE AND NOT {STAFF} THEN
              RAISE EXCEPTION 'you cannot give yourself a clinic role' USING ERRCODE = 'insufficient_privilege';
            END IF;
          ELSIF (NEW.role IS DISTINCT FROM OLD.role OR NEW.user_id IS DISTINCT FROM OLD.user_id)
                AND ((OLD.user_id = rp_user_id()) IS TRUE OR (NEW.user_id = rp_user_id()) IS TRUE
                     OR NOT {STAFF}) THEN
            RAISE EXCEPTION 'clinic roles change only by Radial Pulse staff, never on your own membership'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER clinic_memberships_guard_changes BEFORE INSERT OR UPDATE ON clinic_memberships "
        "FOR EACH ROW EXECUTE FUNCTION rp_guard_membership_changes()"
    )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP TRIGGER IF EXISTS clinic_memberships_guard_changes ON clinic_memberships")
        op.execute("DROP FUNCTION IF EXISTS rp_guard_membership_changes()")
        op.execute("DROP TRIGGER IF EXISTS users_guard_changes ON users")
        op.execute("DROP FUNCTION IF EXISTS rp_guard_user_changes()")
        op.execute("DROP TRIGGER IF EXISTS approvals_guard ON approvals")
        op.execute("DROP FUNCTION IF EXISTS rp_guard_approvals()")
        op.execute("DROP POLICY IF EXISTS internal_review_activity ON audit_events")
        op.execute("DROP POLICY IF EXISTS clinic_sees_published_report_files ON assets")
        op.execute("DROP FUNCTION IF EXISTS rp_report_file_published(uuid, text)")
        op.execute("DROP POLICY IF EXISTS staff_only_reviews ON approvals")

    # Internal notes go back into last_comment (the latest one per approval).
    op.execute(
        """
        UPDATE approvals SET last_comment = (
          SELECT n.body FROM approval_notes n WHERE n.approval_id = approvals.id
          ORDER BY n.created_at DESC, n.id DESC LIMIT 1)
        WHERE EXISTS (SELECT 1 FROM approval_notes n WHERE n.approval_id = approvals.id)
        """
    )
    if _is_postgres():
        op.execute("SET CONSTRAINTS ALL IMMEDIATE")  # see upgrade(): pending checks block ALTER TABLE
    op.drop_index(op.f("ix_approval_notes_clinic_id"), table_name="approval_notes")
    op.drop_index("ix_approval_notes_approval_created", table_name="approval_notes")
    op.drop_table("approval_notes")
    op.drop_column("approvals", "clinic_message")

    op.drop_constraint(op.f("ck_assets_category_only_on_clinic_photos_and_voice"), "assets", type_="check")
    op.drop_constraint(op.f("ck_assets_doctor_labels_only_on_doctor_photos"), "assets", type_="check")
    op.drop_constraint(op.f("ck_assets_practitioner_only_on_doctor_photos"), "assets", type_="check")
    op.drop_index("ix_assets_clinic_practitioner", table_name="assets")
    op.drop_constraint("fk_assets_clinic_practitioner", "assets", type_="foreignkey")
    for column in reversed(LABEL_COLUMNS):
        op.drop_index(f"ix_assets_{column}", table_name="assets")
        op.drop_constraint(op.f(f"fk_assets_{column}_media_taxonomy"), "assets", type_="foreignkey")
        op.drop_column("assets", column)
    op.drop_column("assets", "practitioner_id")
    op.drop_table("media_taxonomy")
