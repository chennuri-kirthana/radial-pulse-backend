from __future__ import annotations

from app.core.enums import ApprovalAction, ApprovalState
from app.services.assets import ALLOWED_MIME_TYPES, storage_key_for
from app.services.governance import REQUIRED_PERMISSION, TRANSITIONS


def test_every_action_has_a_transition_and_permission() -> None:
    assert set(TRANSITIONS) == set(ApprovalAction)
    assert set(REQUIRED_PERMISSION) == set(ApprovalAction)


def test_cannot_approve_a_draft() -> None:
    allowed_from, _ = TRANSITIONS[ApprovalAction.APPROVE]
    assert ApprovalState.DRAFT not in allowed_from


def test_storage_key_is_tenant_prefixed_and_ignores_filenames() -> None:
    import uuid

    from app.core.enums import AssetKind

    clinic, asset = uuid.uuid4(), uuid.uuid4()
    key = storage_key_for(clinic, AssetKind.CLINIC_PHOTO, asset, "image/png")
    assert key == f"clinics/{clinic}/clinic_photo/{asset}.png"
    assert ".." not in key


def test_every_asset_kind_has_allowed_types() -> None:
    from app.core.enums import AssetKind

    assert set(ALLOWED_MIME_TYPES) == set(AssetKind)
