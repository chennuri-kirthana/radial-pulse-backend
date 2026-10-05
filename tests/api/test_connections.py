"""Connected accounts: OAuth start/complete, tokens only in the secret store, disconnect."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from app.db.base import utcnow
from app.models import AuditEvent, PlatformConnection
from tests.conftest import OAUTH_REDIRECT


def _base(clinic_id: object) -> str:
    return f"/api/v1/clinics/{clinic_id}/connections"


def _start(client, auth, user, clinic_id, platform: str = "instagram"):  # type: ignore[no-untyped-def]
    r = client.post(
        f"{_base(clinic_id)}/{platform}/start", headers=auth(user), json={"redirect_uri": OAUTH_REDIRECT}
    )
    assert r.status_code == 200, r.text
    query = parse_qs(urlparse(r.json()["authorization_url"]).query)
    return r.json(), query["state"][0], query


def test_every_platform_is_listed_with_what_is_set_up(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.get(_base(world.clinic_a.id), headers=auth(world.team_member_a))
    assert r.status_code == 200
    cards = {c["platform"]: c for c in r.json()}
    assert set(cards) == {"google_business_profile", "instagram", "facebook", "youtube", "linkedin", "x"}
    assert all(c["status"] == "not_connected" for c in cards.values())
    assert cards["instagram"]["available"] and cards["google_business_profile"]["available"]
    assert not cards["linkedin"]["available"] and not cards["x"]["available"]


def test_connect_instagram_end_to_end(client, db, world, auth, secret_store, oauth_client) -> None:  # type: ignore[no-untyped-def]
    cid = world.clinic_a.id
    _, state, query = _start(client, auth, world.clinic_admin_a, cid)
    assert query["redirect_uri"] == [OAUTH_REDIRECT]
    assert "instagram_basic" in query["scope"][0]
    assert (
        client.get(f"{_base(cid)}/instagram", headers=auth(world.clinic_admin_a)).json()["status"]
        == "pending"
    )

    r = client.post(
        f"{_base(cid)}/instagram/complete",
        headers=auth(world.clinic_admin_a),
        json={"code": "abc", "state": state},
    )
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["status"] == "connected" and card["connected_by_user_id"] == str(world.clinic_admin_a.id)
    assert oauth_client.calls[0]["redirect_uri"] == OAUTH_REDIRECT

    # Tokens are in the secret store …
    (name, secret), = secret_store.secrets.items()  # fmt: skip
    assert name.endswith(f"/connections/{cid}/instagram")
    assert secret["access_token"] == "access-abc"
    # … and nowhere in the database or the audit log.
    db.expire_all()
    row = db.query(PlatformConnection).one()
    assert row.secret_ref and "access-abc" not in str(row.__dict__)
    assert row.oauth_state_hash is None and row.oauth_code_verifier is None
    assert all("access-abc" not in str(e.details) for e in db.query(AuditEvent).all())

    # The same state cannot be used twice.
    again = client.post(
        f"{_base(cid)}/instagram/complete",
        headers=auth(world.clinic_admin_a),
        json={"code": "x", "state": state},
    )
    assert again.status_code == 409


def test_google_uses_pkce(client, world, auth, oauth_client) -> None:  # type: ignore[no-untyped-def]
    cid = world.clinic_a.id
    _, state, query = _start(client, auth, world.dsm_a, cid, "google_business_profile")
    assert query["code_challenge_method"] == ["S256"] and query["access_type"] == ["offline"]
    client.post(
        f"{_base(cid)}/google_business_profile/complete",
        headers=auth(world.dsm_a),
        json={"code": "g", "state": state},
    )
    assert oauth_client.calls[0]["verifier"]  # the verifier went to the token exchange


def test_wrong_state_other_person_or_too_late_is_refused(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    cid = world.clinic_a.id
    _, state, _ = _start(client, auth, world.clinic_admin_a, cid)
    url = f"{_base(cid)}/instagram/complete"
    bad = client.post(url, headers=auth(world.clinic_admin_a), json={"code": "c", "state": "forged"})
    assert bad.status_code == 422
    other = client.post(url, headers=auth(world.dsm_a), json={"code": "c", "state": state})
    assert other.status_code == 422

    row = db.query(PlatformConnection).one()
    row.oauth_started_at = utcnow() - timedelta(hours=1)
    db.commit()
    late = client.post(url, headers=auth(world.clinic_admin_a), json={"code": "c", "state": state})
    assert late.status_code == 409
    assert (
        client.get(f"{_base(cid)}/instagram", headers=auth(world.clinic_admin_a)).json()["status"]
        == "not_connected"
    )


def test_platform_refusal_is_502_and_nothing_is_stored(
    client, world, auth, secret_store, oauth_client
) -> None:  # type: ignore[no-untyped-def]
    cid = world.clinic_a.id
    _, state, _ = _start(client, auth, world.clinic_admin_a, cid)
    oauth_client.fail = True
    r = client.post(
        f"{_base(cid)}/instagram/complete",
        headers=auth(world.clinic_admin_a),
        json={"code": "c", "state": state},
    )
    assert r.status_code == 502
    card = client.get(f"{_base(cid)}/instagram", headers=auth(world.clinic_admin_a)).json()
    assert card["status"] == "not_connected" and card["last_error"]
    assert secret_store.secrets == {}


def test_redirect_must_be_allowed_and_platform_set_up(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    cid = world.clinic_a.id
    h = auth(world.clinic_admin_a)
    evil = client.post(
        f"{_base(cid)}/instagram/start", headers=h, json={"redirect_uri": "https://evil.example"}
    )
    assert evil.status_code == 422
    not_ready = client.post(f"{_base(cid)}/linkedin/start", headers=h, json={"redirect_uri": OAUTH_REDIRECT})
    assert not_ready.status_code == 503


def test_disconnect_deletes_the_tokens(client, world, auth, secret_store) -> None:  # type: ignore[no-untyped-def]
    cid = world.clinic_a.id
    _, state, _ = _start(client, auth, world.clinic_admin_a, cid)
    client.post(
        f"{_base(cid)}/instagram/complete",
        headers=auth(world.clinic_admin_a),
        json={"code": "c", "state": state},
    )
    r = client.post(f"{_base(cid)}/instagram/disconnect", headers=auth(world.clinic_admin_a))
    assert r.status_code == 200 and r.json()["status"] == "disconnected"
    assert secret_store.secrets == {} and len(secret_store.deleted) == 1
    again = client.post(f"{_base(cid)}/instagram/disconnect", headers=auth(world.clinic_admin_a))
    assert again.status_code == 404


def test_reconnecting_keeps_the_account_connected_until_it_finishes(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    cid = world.clinic_a.id
    _, state, _ = _start(client, auth, world.clinic_admin_a, cid)
    client.post(
        f"{_base(cid)}/instagram/complete",
        headers=auth(world.clinic_admin_a),
        json={"code": "c", "state": state},
    )
    _start(client, auth, world.clinic_admin_a, cid)  # press Connect again, never finish
    card = client.get(f"{_base(cid)}/instagram", headers=auth(world.clinic_admin_a)).json()
    assert card["status"] == "connected"


def test_team_member_can_see_but_not_connect(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    cid = world.clinic_a.id
    h = auth(world.team_member_a)
    assert client.get(_base(cid), headers=h).status_code == 200
    r = client.post(f"{_base(cid)}/instagram/start", headers=h, json={"redirect_uri": OAUTH_REDIRECT})
    assert r.status_code == 403
