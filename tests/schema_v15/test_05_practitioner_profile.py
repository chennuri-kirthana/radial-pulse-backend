# ruff: noqa: RUF001  (N20 shows timings with an en dash, exactly as db/tests/05 does)
"""db/tests/05-doctor-profile-tests.sql (N1-N20): the v15 Practitioner Profile fields, on a fresh
v15 database + the Family Dental seed, as the table owner (N11-N13 as the app role, N14 as the
read-only service role)."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest

from tests.schema_v15.helpers import CHECK, MEHUL, POOJA, Db, fresh_database

pytestmark = pytest.mark.integration

D = "'00000000-0000-0000-0000-00000000dd01'"
C = "'00000000-0000-0000-0000-00000000cc01'"
THIS_YEAR = "extract(year FROM current_date)::int"


@pytest.fixture(scope="module")
def db() -> Iterator[Db]:
    with fresh_database("t05", seed=True) as d:
        yield d


@pytest.fixture(autouse=True)
def back_to_owner(db: Db) -> Iterator[None]:
    yield
    db.as_owner()


def test_n01_profile_from_the_seed_with_experience_calculated(db: Db) -> None:
    rows = db.rows(
        f"""SELECT p.full_name, p.specialty, p.qualifications, {THIS_YEAR} - p.practice_start_year,
                   c.name, c.established_year, c.address_line, c.city, c.state, c.postal_code,
                   cp.consultation_hours, cp.weekly_off_days, cp.consultation_fee, cp.consultation_fee_currency,
                   cp.consultation_time_zone, cp.schedule_notes,
                   p.services_and_conditions, p.approx_patients_treated, p.highlights
            FROM practitioners p JOIN clinic_practitioners cp ON cp.practitioner_id = p.id
                 JOIN clinics c ON c.id = cp.clinic_id
            WHERE p.id = {D}"""
    )
    assert len(rows) == 1
    ten_to_two = [{"from": "10:00", "to": "14:00"}]
    assert rows[0] == (
        "Dr. Pooja Shah", "Family Dentistry", "BDS, FAGE", db.one(f"SELECT {THIS_YEAR}") - 2011,
        "Family Dental Clinic", 2008, "12 CG Road", "Ahmedabad", "Gujarat", "380009",
        {"mon": ten_to_two, "tue": ten_to_two, "wed": ten_to_two, "thu": ten_to_two,
         "fri": [{"from": "10:00", "to": "14:00"}, {"from": "17:00", "to": "19:00"}],
         "sat": [{"from": "10:00", "to": "13:00"}], "sun": []},
        ["sun"], Decimal("500.00"), "INR", "Asia/Kolkata", "Emergency appointments on call",
        ["Root canal", "Braces", "Teeth whitening", "Gum disease"], 12000,
        "Gujarat Dental Council award for community dental camps (2019)",
    )  # fmt: skip


def test_n02_practice_start_year_too_old_refused(db: Db) -> None:
    db.error(
        f"UPDATE practitioners SET practice_start_year = 1930 WHERE id = {D}",
        CHECK,
        "ck_practitioners_practice_start_year",
    )


def test_n03_practice_start_year_in_the_future_refused(db: Db) -> None:
    db.error(
        f"UPDATE practitioners SET practice_start_year = {THIS_YEAR} + 1 WHERE id = {D}",
        CHECK,
        "cannot be in the future",
    )


def test_n04_practice_start_year_this_year_allowed(db: Db) -> None:
    assert db.ok(f"UPDATE practitioners SET practice_start_year = {THIS_YEAR} WHERE id = {D}") == 1
    assert db.ok(f"UPDATE practitioners SET practice_start_year = 2011 WHERE id = {D}") == 1


def test_n05_negative_patients_refused(db: Db) -> None:
    db.error(
        f"UPDATE practitioners SET approx_patients_treated = -1 WHERE id = {D}",
        CHECK,
        "ck_practitioners_approx_patients_treated",
    )


def test_n06_empty_or_null_service_refused(db: Db) -> None:
    db.error(
        f"""UPDATE practitioners SET services_and_conditions = '{{"Braces",""}}' WHERE id = {D}""",
        CHECK,
        "ck_practitioners_services_and_conditions",
    )
    db.error(
        f"UPDATE practitioners SET services_and_conditions = ARRAY['Braces', NULL] WHERE id = {D}",
        CHECK,
        "ck_practitioners_services_and_conditions",
    )


def test_n07_weekly_off_days(db: Db) -> None:
    db.error(
        f"UPDATE clinic_practitioners SET weekly_off_days = '{{sunday}}' WHERE practitioner_id = {D}",
        CHECK,
        "ck_clinic_practitioners_weekly_off_days",
    )
    assert (
        db.ok(f"UPDATE clinic_practitioners SET weekly_off_days = '{{sat,sun}}' WHERE practitioner_id = {D}")
        == 1
    )


def test_n08_fee_and_currency(db: Db) -> None:
    db.error(
        f"UPDATE clinic_practitioners SET consultation_fee = -1 WHERE practitioner_id = {D}",
        CHECK,
        "ck_clinic_practitioners_consultation_fee",
    )
    db.error(
        f"UPDATE clinic_practitioners SET consultation_fee_currency = 'inr' WHERE practitioner_id = {D}",
        CHECK,
        "ck_clinic_practitioners_fee_currency",
    )
    assert (
        db.ok(
            f"UPDATE clinic_practitioners SET consultation_fee_currency = 'USD' WHERE practitioner_id = {D}"
        )
        == 1
    )
    assert (
        db.ok(
            f"UPDATE clinic_practitioners SET consultation_fee_currency = 'INR', weekly_off_days = '{{sun}}' WHERE practitioner_id = {D}"
        )
        == 1
    )


def test_n09_clinic_established_year(db: Db) -> None:
    db.error(
        f"UPDATE clinics SET established_year = 1700 WHERE id = {C}", CHECK, "ck_clinics_established_year"
    )
    db.error(
        f"UPDATE clinics SET established_year = {THIS_YEAR} + 1 WHERE id = {C}",
        CHECK,
        "cannot be in the future",
    )
    assert db.ok(f"UPDATE clinics SET established_year = 2008 WHERE id = {C}") == 1


def test_n10_new_fields_are_optional(db: Db) -> None:
    assert (
        db.ok(
            "INSERT INTO clinics (id, client_organization_id, name) VALUES ('00000000-0000-0000-0000-00000000cc09','00000000-0000-0000-0000-00000000bb01','Blank Clinic')"
        )
        == 1
    )
    assert db.ok("DELETE FROM clinics WHERE id = '00000000-0000-0000-0000-00000000cc09'") == 1


def test_n15_old_free_schedule_shape_refused(db: Db) -> None:
    db.error(
        f"""UPDATE clinic_practitioners SET consultation_hours = '{{"mon_sat":"10:00-14:00"}}' WHERE practitioner_id = {D}""",
        CHECK,
        "ck_clinic_practitioners_consultation_hours",
    )


@pytest.mark.parametrize(
    "hours",
    [
        '{"mon":[{"from":"14:00","to":"10:00"}]}',  # from after to
        '{"mon":[{"from":"10:00","to":"25:00"}]}',  # bad time
        '{"mon":[{"from":"10:00","to":"12:00","note":"x"}]}',  # extra key
    ],
)
def test_n16_bad_schedule_slots_refused(db: Db, hours: str) -> None:
    db.error(
        f"UPDATE clinic_practitioners SET consultation_hours = '{hours}' WHERE practitioner_id = {D}",
        CHECK,
        "ck_clinic_practitioners_consultation_hours",
    )


def test_n17_two_slots_or_empty_schedule_allowed(db: Db) -> None:
    assert (
        db.ok(
            f"""UPDATE clinic_practitioners SET consultation_hours = '{{"mon":[{{"from":"09:00","to":"12:00"}},{{"from":"17:00","to":"20:00"}}]}}' WHERE practitioner_id = {D}"""
        )
        == 1
    )
    assert (
        db.ok(f"UPDATE clinic_practitioners SET consultation_hours = '{{}}' WHERE practitioner_id = {D}") == 1
    )


def test_n18_time_zone_must_be_real(db: Db) -> None:
    db.error(
        f"UPDATE clinic_practitioners SET consultation_time_zone = 'Mars/Base' WHERE practitioner_id = {D}",
        CHECK,
        "is not a known time zone",
    )
    assert (
        db.ok(
            f"UPDATE clinic_practitioners SET consultation_time_zone = 'Asia/Dubai' WHERE practitioner_id = {D}"
        )
        == 1
    )


def test_n19_new_clinic_link_gets_defaults(db: Db) -> None:
    db.ok(
        "INSERT INTO practitioners (id, full_name) VALUES ('00000000-0000-0000-0000-00000000dd09','Dr. Test')"
    )
    db.ok(
        f"INSERT INTO clinic_practitioners (clinic_id, practitioner_id) VALUES ({C}, '00000000-0000-0000-0000-00000000dd09')"
    )
    assert db.one(
        "SELECT consultation_hours, weekly_off_days, consultation_fee_currency, consultation_time_zone "
        "FROM clinic_practitioners WHERE practitioner_id = '00000000-0000-0000-0000-00000000dd09'"
    ) == ({}, [], "INR", "Asia/Kolkata")
    assert db.ok("DELETE FROM practitioners WHERE id = '00000000-0000-0000-0000-00000000dd09'") == 1


def test_n20_seven_weekdays_with_slots_or_no_consultation(db: Db) -> None:
    db.ok(
        f"""UPDATE clinic_practitioners SET consultation_hours = '{{"mon":[{{"from":"10:00","to":"14:00"}}],"fri":[{{"from":"10:00","to":"14:00"}},{{"from":"17:00","to":"19:00"}}]}}' WHERE practitioner_id = {D}"""
    )
    rows = db.rows(
        f"""SELECT d.day, coalesce((SELECT string_agg((s->>'from') || '–' || (s->>'to'), ', ')
                                     FROM jsonb_array_elements(cp.consultation_hours->d.day) s), 'No consultation')
            FROM clinic_practitioners cp,
                 unnest(ARRAY['mon','tue','wed','thu','fri','sat','sun']) WITH ORDINALITY AS d(day, n)
            WHERE cp.practitioner_id = {D} ORDER BY d.n"""
    )
    assert rows == [
        ("mon", "10:00–14:00"), ("tue", "No consultation"), ("wed", "No consultation"),
        ("thu", "No consultation"), ("fri", "10:00–14:00, 17:00–19:00"),
        ("sat", "No consultation"), ("sun", "No consultation"),
    ]  # fmt: skip


# ------------------------------------------------------------------- access rules (v15 fields)
def test_n11_practitioner_edits_own_highlights_and_services(db: Db) -> None:
    db.as_user(POOJA)
    assert (
        db.ok(
            f"""UPDATE practitioners SET highlights = 'Updated by Dr Pooja', services_and_conditions = '{{"Root canal","Braces"}}' WHERE id = {D}"""
        )
        == 1
    )


def test_n12_practitioner_cannot_edit_own_fee(db: Db) -> None:
    db.as_user(POOJA)
    assert db.ok(f"UPDATE clinic_practitioners SET consultation_fee = 1 WHERE practitioner_id = {D}") == 0


def test_n13_clinic_admin_sets_fee_and_weekly_off(db: Db) -> None:
    db.as_user(MEHUL)
    assert (
        db.ok(
            f"UPDATE clinic_practitioners SET consultation_fee = 600, weekly_off_days = '{{sun}}' WHERE practitioner_id = {D}"
        )
        == 1
    )


def test_n14_service_role_sees_the_new_fields(db: Db) -> None:
    db.ok("SET ROLE radial_service")
    rows = db.rows(
        f"""SELECT p.full_name, p.practice_start_year, p.highlights, cp.consultation_fee, cp.weekly_off_days, c.established_year
            FROM practitioners p JOIN clinic_practitioners cp ON cp.practitioner_id = p.id JOIN clinics c ON c.id = cp.clinic_id
            WHERE p.id = {D}"""
    )
    assert rows == [("Dr. Pooja Shah", 2011, "Updated by Dr Pooja", Decimal("600.00"), ["sun"], 2008)]
