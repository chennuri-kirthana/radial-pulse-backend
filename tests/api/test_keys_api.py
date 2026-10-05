"""Natural keys seen through the API: one doctor record per registration number per business."""

from __future__ import annotations


def test_same_registration_number_in_one_business_is_a_409_with_the_way_out(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    path = f"/api/v1/clinics/{world.clinic_a.id}/practitioners"
    h = auth(world.dsm_a)
    first = client.post(
        path, headers=h, json={"full_name": "Dr. Neha Gupta", "registration_number": "TS-1234"}
    )
    assert first.status_code == 201, first.text
    again = client.post(path, headers=h, json={"full_name": "Dr. N. Gupta", "registration_number": "TS-1234"})
    assert again.status_code == 409
    assert first.json()["id"] in again.json()["detail"]  # tells you which doctor to link instead

    # Changing another doctor to that number is refused too …
    other = client.post(path, headers=h, json={"full_name": "Dr. Ravi", "registration_number": "TS-9999"})
    r = client.patch(f"{path}/{other.json()['id']}", headers=h, json={"registration_number": "TS-1234"})
    assert r.status_code == 409
    # … but a doctor may keep (re-save) their own number, and doctors without a number are fine.
    r = client.patch(f"{path}/{first.json()['id']}", headers=h, json={"registration_number": "TS-1234"})
    assert r.status_code == 200
    for name in ("Dr. No Number 1", "Dr. No Number 2"):
        assert client.post(path, headers=h, json={"full_name": name}).status_code == 201


def test_another_business_may_use_the_same_registration_number(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    body = {"full_name": "Dr. Same Number", "registration_number": "TS-5555"}
    a = client.post(
        f"/api/v1/clinics/{world.clinic_a.id}/practitioners", headers=auth(world.admin), json=body
    )
    b = client.post(
        f"/api/v1/clinics/{world.clinic_b.id}/practitioners", headers=auth(world.admin), json=body
    )
    assert a.status_code == 201 and b.status_code == 201
