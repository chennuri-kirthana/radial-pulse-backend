"""The Digital Presence Assessment: request → background job → engines → one unified result."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.assessments.engines import (
    ComponentResult,
    DiscoveredProfile,
    EngineInput,
    EngineRegistry,
    Evidence,
    FindingResult,
)
from app.core.enums import (
    AssessmentComponentKey,
    ComponentStatus,
    FindingPriority,
    JobStatus,
    PresencePlatform,
    PresenceVerification,
)
from app.models import AuditEvent, BackgroundJob, PresenceProfile
from app.worker.runner import Outcome, process_message

NOW = datetime(2026, 9, 25, 6, 0, tzinfo=UTC)


class FakeEngine:
    """Test double for a domain team's engine (records what it was given)."""

    def __init__(self, component: AssessmentComponentKey, result: Any, name: str = "fake-engine") -> None:
        self.component = component
        self.name = name
        self.version = "0.0.1"
        self._result = result
        self.inputs: list[EngineInput] = []

    def assess(self, data: EngineInput) -> ComponentResult:
        self.inputs.append(data)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def website_result() -> ComponentResult:
    return ComponentResult(
        status=ComponentStatus.COMPLETED,
        score=60,
        summary="Website loads but misses basics.",
        findings=[
            FindingResult(
                code="website.missing_meta_description",
                title="Home page has no meta description",
                priority=FindingPriority.HIGH,
                recommendation="Add a 150-character description mentioning your city and services.",
                evidence=[
                    Evidence(
                        source_url="https://smile.example.com/",
                        excerpt="<head>…no meta description…</head>",
                        provider="http-fetch",
                        observed_at=NOW,
                    )
                ],
            )
        ],
        discovered_profiles=[
            DiscoveredProfile(
                platform=PresencePlatform.INSTAGRAM,
                url="https://instagram.com/smiledental",
                confidence=0.9,
                evidence=[
                    Evidence(source_url="https://smile.example.com/", provider="http-fetch", observed_at=NOW)
                ],
            )
        ],
    )


def _request(client, world, auth):  # type: ignore[no-untyped-def]
    r = client.post(f"/api/v1/clinics/{world.clinic_a.id}/assessments", headers=auth(world.dsm_a), json={})
    assert r.status_code == 202, r.text
    return r.json()


def test_request_creates_one_assessment_a_job_and_a_queue_message(client, db, world, auth, job_queue) -> None:  # type: ignore[no-untyped-def]
    body = _request(client, world, auth)
    assert body["status"] == "queued"
    assert body["sequence"] == 1
    assert len(job_queue.messages) == 1
    msg = job_queue.messages[0]
    assert str(msg.clinic_id) == str(world.clinic_a.id)
    job = db.get(BackgroundJob, msg.job_id)
    assert job.status is JobStatus.QUEUED and str(job.resource_id) == body["id"]
    detail = client.get(
        f"/api/v1/clinics/{world.clinic_a.id}/assessments/{body['id']}", headers=auth(world.dsm_a)
    )
    keys = [c["key"] for c in detail.json()["components"]]
    assert keys == [k.value for k in AssessmentComponentKey]  # the fixed, unified sections
    # A second request while one is in progress is refused.
    r = client.post(f"/api/v1/clinics/{world.clinic_a.id}/assessments", headers=auth(world.dsm_a), json={})
    assert r.status_code == 409


def test_worker_builds_the_unified_assessment(client, db, world, auth, job_queue, session_factory) -> None:  # type: ignore[no-untyped-def]
    db.query(PresenceProfile)  # warm
    body = _request(client, world, auth)
    website = FakeEngine(AssessmentComponentKey.WEBSITE, website_result())
    gbp = FakeEngine(
        AssessmentComponentKey.GOOGLE_BUSINESS_PROFILE,
        ComponentResult(status=ComponentStatus.COMPLETED, score=80, summary="Listing is complete."),
    )
    engines = EngineRegistry()
    engines.register(website)
    engines.register(gbp)

    assert process_message(session_factory, job_queue.messages[0], engines) is Outcome.DONE
    assert website.inputs[0].clinic_name == "Smile Dental A"

    detail = client.get(
        f"/api/v1/clinics/{world.clinic_a.id}/assessments/{body['id']}", headers=auth(world.dsm_a)
    ).json()
    assert detail["status"] == "partial"  # 2 of 6 components have engines today
    assert detail["overall_score"] == 70.0  # placeholder methodology: mean of completed components
    comps = {c["key"]: c for c in detail["components"]}
    assert comps["website"]["engine_name"] == "fake-engine"
    finding = comps["website"]["findings"][0]
    assert finding["priority"] == "high"
    assert finding["evidence"][0]["source_url"] == "https://smile.example.com/"
    assert comps["social_presence"]["status"] == "not_available"
    assert comps["social_presence"]["status_reason"] == "no_engine_deployed"

    # The finder part: discovered profiles land as UNVERIFIED, attributed to the engine.
    found = db.query(PresenceProfile).filter_by(clinic_id=world.clinic_a.id).one()
    assert found.verification is PresenceVerification.UNVERIFIED
    assert found.discovered_by == "service:fake-engine"
    # Service identity is recorded as such in the audit trail.
    event = db.query(AuditEvent).filter_by(action="assessment.generated").one()
    assert event.actor_type == "service" and event.actor_user_id is None
    assert event.details["service"] == "assessment-worker"


def test_duplicate_messages_are_harmless(client, db, world, auth, job_queue, session_factory) -> None:  # type: ignore[no-untyped-def]
    _request(client, world, auth)
    msg = job_queue.messages[0]
    engines = EngineRegistry()
    engines.register(FakeEngine(AssessmentComponentKey.WEBSITE, website_result()))
    assert process_message(session_factory, msg, engines) is Outcome.DONE
    assert process_message(session_factory, msg, engines) is Outcome.SKIP  # at-least-once delivery
    assert db.query(AuditEvent).filter_by(action="assessment.generated").count() == 1


def test_failures_retry_then_give_up(client, db, world, auth, job_queue, session_factory) -> None:  # type: ignore[no-untyped-def]
    body = _request(client, world, auth)
    msg = job_queue.messages[0]

    class BoomError(RuntimeError):
        pass

    engines = EngineRegistry()
    engines.register(FakeEngine(AssessmentComponentKey.WEBSITE, BoomError("provider timeout")))
    job = db.get(BackgroundJob, msg.job_id)
    job.max_attempts = 2
    db.commit()

    assert process_message(session_factory, msg, engines) is Outcome.RETRY
    db.expire_all()
    assert db.get(BackgroundJob, msg.job_id).status is JobStatus.QUEUED
    assert process_message(session_factory, msg, engines) is Outcome.DONE
    db.expire_all()
    job = db.get(BackgroundJob, msg.job_id)
    assert job.status is JobStatus.FAILED and job.attempts == 2
    assert "provider timeout" in job.last_error
    detail = client.get(
        f"/api/v1/clinics/{world.clinic_a.id}/assessments/{body['id']}", headers=auth(world.dsm_a)
    )
    assert detail.json()["status"] == "failed"


def test_invalid_engine_output_fails_only_that_component(
    client, world, auth, job_queue, session_factory
) -> None:  # type: ignore[no-untyped-def]
    body = _request(client, world, auth)

    class Sloppy:
        name, version, component = "sloppy", "1", AssessmentComponentKey.WEBSITE

        def assess(self, data: EngineInput) -> ComponentResult:
            # model_construct skips validation — the platform must catch this itself.
            return ComponentResult.model_construct(status=ComponentStatus.COMPLETED, score=500, findings=[])

    engines = EngineRegistry()
    engines.register(Sloppy())
    assert process_message(session_factory, job_queue.messages[0], engines) is Outcome.DONE
    comps = {
        c["key"]: c
        for c in client.get(
            f"/api/v1/clinics/{world.clinic_a.id}/assessments/{body['id']}", headers=auth(world.dsm_a)
        ).json()["components"]
    }
    assert comps["website"]["status"] == "failed"
    assert comps["website"]["status_reason"] == "invalid_engine_output"


def test_high_priority_findings_need_evidence() -> None:
    with pytest.raises(ValueError, match="evidence"):
        FindingResult(code="website.x_y", title="t", priority=FindingPriority.CRITICAL)


def test_clinic_admin_sees_only_published_and_review_flow(
    client, world, auth, job_queue, session_factory
) -> None:  # type: ignore[no-untyped-def]
    body = _request(client, world, auth)
    base = f"/api/v1/clinics/{world.clinic_a.id}"

    def act(user, action):  # type: ignore[no-untyped-def]
        return client.post(
            f"{base}/approvals/actions",
            headers=auth(user),
            json={"resource_type": "assessment", "resource_id": body["id"], "action": action},
        )

    assert act(world.dsm_a, "submit").status_code == 409  # not finished yet
    engines = EngineRegistry()
    engines.register(FakeEngine(AssessmentComponentKey.WEBSITE, website_result()))
    process_message(session_factory, job_queue.messages[0], engines)

    assert client.get(f"{base}/assessments", headers=auth(world.clinic_admin_a)).json()["total"] == 0
    # Clinic staff (Team Members) follow the same gate.
    assert client.get(f"{base}/assessments", headers=auth(world.team_member_a)).json()["total"] == 0
    r = client.get(f"{base}/assessments/{body['id']}", headers=auth(world.team_member_a))
    assert r.status_code == 404
    assert act(world.dsm_a, "submit").status_code == 200
    assert act(world.team_member_a, "approve").status_code == 403
    # The publication gate: a Clinic Administrator can never approve/reject an assessment.
    assert act(world.clinic_admin_a, "approve").status_code == 403
    assert act(world.clinic_admin_a, "reject").status_code == 403
    assert act(world.dsm_a, "approve").status_code == 200
    assert act(world.dsm_a, "publish").json()["publication_state"] == "published"
    # ...and can never pull back ("redo" = retract) a published one.
    assert act(world.clinic_admin_a, "redo").status_code == 403
    listed = client.get(f"{base}/assessments", headers=auth(world.clinic_admin_a)).json()
    assert listed["total"] == 1
    assert client.get(f"{base}/assessments", headers=auth(world.team_member_a)).json()["total"] == 1
    detail = client.get(f"{base}/assessments/{body['id']}", headers=auth(world.clinic_admin_a)).json()
    assert detail["published_at"] is not None and detail["overall_score"] == 60.0
    # Every time the clinic opens its report, it is in the audit log (staff views are not).
    client.get(f"{base}/assessments/{body['id']}", headers=auth(world.dsm_a))
    viewed = client.get(f"{base}/audit-events", headers=auth(world.dsm_a)).json()["items"]
    assert [e["action"] for e in viewed].count("assessment.viewed") == 1
    # Other clinics never see it.
    assert (
        client.get(f"{base}/assessments/{body['id']}", headers=auth(world.clinic_admin_b)).status_code == 404
    )


def test_worker_cannot_touch_another_clinic(client, db, world, auth, job_queue, session_factory) -> None:  # type: ignore[no-untyped-def]
    """A message whose clinic_id does not match the job is skipped (no cross-tenant work)."""
    from app.jobs.queue import JobMessage

    _request(client, world, auth)
    real = job_queue.messages[0]
    forged = JobMessage(job_id=real.job_id, clinic_id=world.clinic_b.id, job_type=real.job_type)
    assert process_message(session_factory, forged, EngineRegistry()) is Outcome.SKIP
    db.expire_all()
    assert db.get(BackgroundJob, real.job_id).status is JobStatus.QUEUED
