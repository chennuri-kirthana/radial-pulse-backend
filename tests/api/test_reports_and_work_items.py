"""Areas E8 + E9: Digital Presence Assessments and Improvement Work Items (docs/01 sections 8 + 9)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Notification
from tests.factories import World, build_world

pytestmark = pytest.mark.integration

CLINIC_SIDE = ["clinic_admin", "team_member", "practitioner"]


@pytest.fixture
def world(db: Session) -> World:
    return build_world(db)


def reports(world: World, tail: str = "") -> str:
    return f"/api/v1/clinics/{world.clinic_a.id}/digital-presence-assessments{tail}"


def items(world: World, tail: str = "") -> str:
    return f"/api/v1/clinics/{world.clinic_a.id}/improvement-work-items{tail}"


def new_report(client: TestClient, auth, world: World, **body: Any) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    r = client.post(
        reports(world), json={"status": "completed", "overall_score": 72.5, **body}, headers=auth(world.dsm_a)
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


# ------------------------------------------------------------------ reports
def test_report_life_draft_review_publish_retract(
    client: TestClient, auth, world: World, db: Session
) -> None:  # type: ignore[no-untyped-def]
    rep = new_report(client, auth, world, summary="Good start")
    assert (rep["review_state"], rep["publication_state"], rep["overall_score"]) == (
        "draft",
        "unpublished",
        "72.50",
    )
    h = auth(world.dsm_a)
    one = reports(world, f"/{rep['id']}")
    # clinic side can't see a draft
    for who in CLINIC_SIDE:
        assert client.get(reports(world), headers=auth(world.people_a()[who])).json() == []
        assert client.get(one, headers=auth(world.people_a()[who])).status_code == 404
    assert client.post(f"{one}/publish", headers=h).status_code == 409  # not approved yet
    approved = client.post(f"{one}/review", json={"review_state": "approved"}, headers=h).json()
    assert approved["reviewed_at"] is not None
    published = client.post(f"{one}/publish", headers=h).json()
    assert (published["publication_state"], published["published_at"] is not None) == ("published", True)
    for who in CLINIC_SIDE:
        assert [r["id"] for r in client.get(reports(world), headers=auth(world.people_a()[who])).json()] == [
            rep["id"]
        ]
    assert client.post(f"{one}/review", json={"review_state": "rejected"}, headers=h).status_code == 409
    assert client.post(f"{one}/retract", headers=h).json()["publication_state"] == "retracted"
    assert client.get(one, headers=auth(world.clinic_admin_a)).status_code == 404
    actions = set(db.scalars(select(AuditEvent.action)))
    assert {"digital_presence_assessment.approved", "digital_presence_assessment.published"} <= actions


def test_one_report_in_progress_per_clinic(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    new_report(client, auth, world, status="queued")
    r = client.post(reports(world), json={"status": "running"}, headers=auth(world.admin))
    assert (r.status_code, r.json()["code"]) == (409, "state_conflict")


@pytest.mark.parametrize("who", CLINIC_SIDE)
def test_only_staff_manage_reports(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    rep = new_report(client, auth, world)
    h = auth(world.people_a()[who])
    assert client.post(reports(world), json={}, headers=h).status_code == 403
    assert (
        client.post(
            reports(world, f"/{rep['id']}/review"), json={"review_state": "approved"}, headers=h
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "body",
    [
        {"overall_score": 101},
        {"status": "partial"},
        {"review_state": "approved"},
        {"digital_growth_report_id": "x" * 129},
    ],
)
def test_report_bad_input(client: TestClient, auth, world: World, body: dict) -> None:  # type: ignore[no-untyped-def,type-arg]
    assert client.post(reports(world), json=body, headers=auth(world.dsm_a)).status_code == 400


def test_reports_other_clinic_and_bad_review(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    rep = new_report(client, auth, world)
    assert client.get(reports(world), headers=auth(world.dsm_b)).status_code == 404
    bad = client.post(
        reports(world, f"/{rep['id']}/review"), json={"review_state": "draft"}, headers=auth(world.dsm_a)
    )
    assert bad.status_code == 400
    assert client.get(reports(world, f"/{uuid.uuid4()}"), headers=auth(world.dsm_a)).status_code == 404


# ------------------------------------------------------------------ work items
def test_staff_create_assign_and_finish_a_work_item(
    client: TestClient, auth, world: World, db: Session
) -> None:  # type: ignore[no-untyped-def]
    body = {
        "title": "Claim Google listing",
        "priority": "high",
        "assignee_user_id": str(world.clinic_admin_a.id),
    }
    r = client.post(items(world), json=body, headers=auth(world.dsm_a))
    assert r.status_code == 201, r.text
    item = r.json()
    assert db.scalars(
        select(Notification.category).where(Notification.user_id == world.clinic_admin_a.id)
    ).all() == ["work_item_assigned"]
    done = client.patch(
        items(world, f"/{item['id']}"), json={"status": "done"}, headers=auth(world.dsm_a)
    ).json()
    assert done["completed_at"] is not None
    reopened = client.patch(
        items(world, f"/{item['id']}"), json={"status": "in_progress"}, headers=auth(world.dsm_a)
    ).json()
    assert reopened["completed_at"] is None


def test_practitioner_sees_only_his_own_items(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.dsm_a)
    mine = client.post(
        items(world),
        json={"title": "Record a voice sample", "assignee_user_id": str(world.practitioner_login_a.id)},
        headers=h,
    ).json()
    other = client.post(items(world), json={"title": "Fix website"}, headers=h).json()
    p = auth(world.practitioner_login_a)
    assert [i["id"] for i in client.get(items(world), headers=p).json()] == [mine["id"]]
    assert client.get(items(world, f"/{other['id']}"), headers=p).status_code == 404
    team = client.get(items(world), headers=auth(world.team_member_a)).json()
    assert {i["id"] for i in team} == {mine["id"], other["id"]}


def test_fix_now_items_need_a_code_and_are_unique_while_open(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    rep = new_report(client, auth, world)
    h = auth(world.dsm_a)
    no_code = {"title": "Fix", "source_assessment_id": rep["id"]}
    assert client.post(items(world), json=no_code, headers=h).status_code == 400
    fix = {**no_code, "opportunity_code": "gbp.unclaimed"}
    assert client.post(items(world), json=fix, headers=h).status_code == 201
    second = client.post(items(world), json=fix, headers=h)
    assert (second.status_code, second.json()["code"]) == (409, "state_conflict")


@pytest.mark.parametrize("who", CLINIC_SIDE)
def test_only_staff_change_improvement_work_items(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    assert (
        client.post(items(world), json={"title": "X"}, headers=auth(world.people_a()[who])).status_code == 403
    )


def test_work_item_rules(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.dsm_a)
    outsider = client.post(
        items(world), json={"title": "X", "assignee_user_id": str(world.clinic_admin_b.id)}, headers=h
    )
    assert (outsider.status_code, outsider.json()["code"]) == (
        409,
        "state_conflict",
    )  # trigger: not in this clinic
    assert client.post(items(world), json={"title": ""}, headers=h).status_code == 400
    assert client.post(items(world), json={"title": "X", "status": "open"}, headers=h).status_code == 400
    assert client.get(items(world), headers=auth(world.dsm_b)).status_code == 404
