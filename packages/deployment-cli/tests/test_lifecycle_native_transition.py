from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_enrollment import installation_key_id
from fdai_deployment_cli.lifecycle_native_transition import (
    NativeScopeTransitionApproval,
    NativeScopeTransitionRequest,
    hub_key_id,
    sign_transition_approval,
    sign_transition_request,
)
from pydantic import ValidationError

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


def request(key: Ed25519PrivateKey) -> NativeScopeTransitionRequest:
    public = key.public_key().public_bytes_raw()
    values = {
        "schema_version": "fdai.lifecycle-native-transition-request.v1",
        "request_id": uuid4(),
        "installation_id": "installation-alpha",
        "old_entity_id": "operator-hub-canary",
        "new_entity_id": "fdai-workloads",
        "old_scope_digest": "sha256:" + "a" * 64,
        "new_scope_digest": "sha256:" + "b" * 64,
        "old_reported_state_digest": "c" * 64,
        "ownership_claim_digest": "sha256:" + "d" * 64,
        "recovery_request_digest": "sha256:" + "e" * 64,
        "recovered_identity_key_id": installation_key_id(public),
        "existing_resources_digest": "sha256:" + "f" * 64,
        "requested_at": NOW,
        "expires_at": NOW + timedelta(minutes=10),
        "confirmation": "",
    }
    confirmation = (
        f"transition native scope {values['installation_id']} "
        f"{values['old_scope_digest']} {values['new_scope_digest']}"
    )
    return NativeScopeTransitionRequest(**(values | {"confirmation": confirmation}))


def test_recovered_request_and_hub_approval_bind_every_transition_digest() -> None:
    installation_key = Ed25519PrivateKey.generate()
    hub_key = Ed25519PrivateKey.generate()
    signed_request = sign_transition_request(request(installation_key), installation_key)
    hub_public = hub_key.public_key().public_bytes_raw()
    approval = NativeScopeTransitionApproval(
        schema_version="fdai.lifecycle-native-transition-approval.v1",
        request=signed_request,
        profile="full-authority-development",
        approved_by="owner",
        approved_at=NOW + timedelta(minutes=1),
        expires_at=signed_request.request.expires_at,
        recovery_audit_digest="sha256:" + "1" * 64,
        ownership_audit_digest="sha256:" + "2" * 64,
        hub_key_id=hub_key_id(hub_public),
        hub_key_epoch=3,
    )
    signed_approval = sign_transition_approval(approval, hub_key)

    assert signed_request.verify(installation_key.public_key().public_bytes_raw())
    assert signed_approval.verify(
        hub_public,
        key_id=approval.hub_key_id,
        key_epoch=approval.hub_key_epoch,
    )
    assert not signed_request.verify(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
    assert not signed_approval.verify(hub_public, key_id=approval.hub_key_id, key_epoch=4)
    assert signed_request.request.recovered_identity_key_id in approval.payload.decode("ascii")


@pytest.mark.parametrize("change", ["same-scope", "same-entity", "expired", "confirmation"])
def test_transition_request_rejects_ambiguous_or_expired_authority(change: str) -> None:
    key = Ed25519PrivateKey.generate()
    original = request(key)
    updates = {
        "same-scope": {"new_scope_digest": original.old_scope_digest},
        "same-entity": {"new_entity_id": original.old_entity_id},
        "expired": {"expires_at": original.requested_at + timedelta(minutes=11)},
        "confirmation": {"confirmation": "transition"},
    }[change]
    with pytest.raises(ValidationError):
        NativeScopeTransitionRequest.model_validate(original.model_dump(mode="json") | updates)
