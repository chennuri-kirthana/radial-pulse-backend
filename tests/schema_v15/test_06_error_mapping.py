"""Database refusal → API error (CLAUDE.md error table), using REAL PostgreSQL errors from v15.

Each case makes the database say no, then checks what ``app.core.db_errors.app_error_for``
turns it into. Runs on its own fresh database + the Family Dental seed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from app.core.db_errors import VOICE_TITLE_MESSAGE, app_error_for
from app.core.errors import AppError
from tests.schema_v15.helpers import ANIL, CLINIC, MEHUL, PRACTITIONER, Db, fresh_database

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def db() -> Iterator[Db]:
    with fresh_database("t06", seed=True) as d:
        yield d


@pytest.fixture(autouse=True)
def _owner_after_each(db: Db) -> Iterator[None]:
    yield
    db.as_owner()


def refusal(db: Db, sql: str) -> AppError | None:
    with pytest.raises(psycopg.Error) as caught:
        db.conn.execute(sql.encode())
    return app_error_for(caught.value)


def test_guard_trigger_is_403_with_its_message(db: Db) -> None:
    db.as_user(MEHUL)  # Clinic Administrator: may edit the clinic, not move its stage
    err = refusal(
        db, f"UPDATE clinics SET stage = 'client_discussion' WHERE id = '{CLINIC}'"
    )  # seed: active_client
    assert err is not None and (err.status_code, err.code) == (403, "forbidden")
    assert (
        err.detail
        == "only the DSM or a Platform Administrator can change stage, archive or Client Organization"
    )


def test_row_level_security_is_403_without_table_names(db: Db) -> None:
    db.as_user(MEHUL)  # only a Platform Administrator creates Client Organizations
    err = refusal(db, "INSERT INTO client_organizations (name) VALUES ('Not mine')")
    assert err is not None and (err.status_code, err.code, err.detail) == (403, "forbidden", None)


def test_unique_is_409_state_conflict(db: Db) -> None:
    email = db.one(f"SELECT email FROM users WHERE id = '{ANIL}'")
    err = refusal(
        db, f"INSERT INTO users (email, platform_role) VALUES ('{email}', 'platform_administrator')"
    )
    assert err is not None and (err.status_code, err.code) == (409, "state_conflict")
    assert email not in (err.detail or "")  # the failing row is never echoed


def test_duplicate_voice_title_has_its_own_message(db: Db) -> None:
    def insert(title: str) -> str:
        vid = uuid.uuid4()
        return (
            "INSERT INTO voice_samples (id, clinic_id, practitioner_id, title, original_key, mime_type, size_bytes) "
            f"VALUES ('{vid}', '{CLINIC}', '{PRACTITIONER}', '{title}', 'clinics/{CLINIC}/voice/{vid}.m4a', "
            "'audio/mp4', 10)"
        )

    db.ok(insert("Welcome"))
    err = refusal(db, insert("welcome"))  # same title, other case
    assert err is not None and (err.status_code, err.code, err.detail) == (
        409,
        "state_conflict",
        VOICE_TITLE_MESSAGE,
    )


def test_foreign_key_is_409(db: Db) -> None:
    err = refusal(db, f"INSERT INTO clinics (client_organization_id, name) VALUES ('{uuid.uuid4()}', 'X')")
    assert err is not None and (err.status_code, err.code) == (409, "state_conflict")


def test_check_rule_is_400_with_the_column_as_field(db: Db) -> None:
    err = refusal(db, f"UPDATE clinics SET country = 'in' WHERE id = '{CLINIC}'")
    assert err is not None and (err.status_code, err.code) == (400, "invalid_request")
    assert err.fields is not None and list(err.fields) == ["country"]


def test_year_in_the_future_is_400_with_field(db: Db) -> None:
    err = refusal(db, f"UPDATE practitioners SET practice_start_year = 2099 WHERE id = '{PRACTITIONER}'")
    assert err is not None and (err.status_code, err.code) == (400, "invalid_request")
    assert err.fields is not None and list(err.fields) == ["practice_start_year"]


def test_unknown_time_zone_is_400_with_field(db: Db) -> None:
    err = refusal(
        db,
        f"UPDATE clinic_practitioners SET consultation_time_zone = 'Mars/Olympus' "
        f"WHERE clinic_id = '{CLINIC}' AND practitioner_id = '{PRACTITIONER}'",
    )
    assert err is not None and (err.status_code, err.code) == (400, "invalid_request")
    assert err.fields is not None and list(err.fields) == ["consultation_time_zone"]


def test_business_trigger_is_409_with_its_message(db: Db) -> None:
    # A clinic-member login that is not a member of THIS clinic can't be the assignee
    outsider = uuid.uuid4()
    db.ok(
        f"INSERT INTO users (id, email, platform_role) VALUES ('{outsider}', 'out-{outsider}@x.test', 'clinic_member')"
    )
    err = refusal(
        db,
        f"INSERT INTO improvement_work_items (clinic_id, title, assignee_user_id) VALUES ('{CLINIC}', 'T', '{outsider}')",
    )
    assert err is not None and (err.status_code, err.code) == (409, "state_conflict")
    assert err.detail is not None and "does not belong to clinic" in err.detail


def test_not_null_is_400_with_field(db: Db) -> None:
    err = refusal(db, "INSERT INTO client_organizations (name) VALUES (NULL)")
    assert err is not None and (err.status_code, err.code) == (400, "invalid_request")
    assert err.fields == {"name": "This value is required."}


def test_other_database_errors_are_not_mapped(db: Db) -> None:
    assert refusal(db, "SELECT 1 / 0") is None  # becomes a plain 500
