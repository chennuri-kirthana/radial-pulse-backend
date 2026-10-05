from __future__ import annotations

from app.core.enums import PresencePlatform, PresenceVerification
from app.models import PresenceProfile


def test_add_list_and_verify_presence_profiles(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    base = f"/api/v1/clinics/{world.clinic_a.id}/presence-profiles"
    r = client.post(
        base,
        headers=auth(world.clinic_admin_a),
        json={"platform": "google_business_profile", "url": "https://maps.google.com/?cid=123"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["verification"] == "confirmed"  # a person asserted it
    dup = client.post(
        base,
        headers=auth(world.dsm_a),
        json={"platform": "google_business_profile", "url": "https://maps.google.com/?cid=123"},
    )
    assert dup.status_code == 409

    found = PresenceProfile(
        clinic_id=world.clinic_a.id,
        platform=PresencePlatform.FACEBOOK,
        url="https://facebook.com/somebody-else",
        discovered_by="service:finder",
        evidence={"items": []},
    )
    db.add(found)
    db.commit()
    r = client.patch(f"{base}/{found.id}", headers=auth(world.dsm_a), json={"verification": "rejected"})
    assert r.json()["verification"] == "rejected"
    db.expire_all()
    assert db.get(PresenceProfile, found.id).verification is PresenceVerification.REJECTED

    listed = client.get(base, headers=auth(world.clinic_admin_a)).json()
    assert listed["total"] == 2
    # Another clinic cannot see or change them.
    assert client.get(base, headers=auth(world.clinic_admin_b)).status_code == 404
    other = f"/api/v1/clinics/{world.clinic_b.id}/presence-profiles/{found.id}"
    assert (
        client.patch(
            other, headers=auth(world.clinic_admin_b), json={"verification": "confirmed"}
        ).status_code
        == 404
    )
