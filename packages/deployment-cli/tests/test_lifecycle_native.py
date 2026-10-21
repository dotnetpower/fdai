from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from fdai_deployment_cli.lifecycle_native import (
    NativeApproval,
    NativeScope,
    NativeScopeClaim,
    sign_native_scope,
)


def scope(**overrides):
    return NativeScope(
        **(
            {
                "installation_id": "installation-alpha",
                "entity_id": "application",
                "product": "example-web",
                "namespace": "example-test",
                "components": ("frontend",),
            }
            | overrides
        )
    )


@pytest.mark.parametrize("components", [(), ("b", "a"), ("a", "a")])
def test_scope_requires_nonempty_canonical_component_names(components):
    with pytest.raises(ValidationError):
        scope(components=components)


def test_anchor_is_stable_but_approval_scope_binds_every_private_target():
    original = scope()
    changed = scope(namespace="another-test")
    assert original.anchor_name == changed.anchor_name
    assert original.digest != changed.digest
    assert scope(entity_id="other").anchor_name != original.anchor_name
    assert scope(installation_id="other").anchor_name != original.anchor_name
    assert original.resources == frozenset({("Deployment", "frontend"), ("Service", "frontend")})
    with pytest.raises(ValidationError):
        scope(components=(original.anchor_name,))


@pytest.mark.parametrize("hours", [0, -1, 4.01])
def test_approval_duration_cannot_be_unbounded(hours):
    now = datetime(2026, 10, 5, tzinfo=UTC)
    with pytest.raises(ValidationError):
        NativeApproval(
            schema_version="fdai.lifecycle-native-approval.v1",
            scope=scope(),
            profile="full-authority-development",
            approved_by="owner",
            approved_at=now,
            expires_at=now + timedelta(hours=hours),
        )


def test_signature_cannot_be_retargeted_and_does_not_accept_another_installation_key():
    key = Ed25519PrivateKey.generate()
    claim = NativeScopeClaim(
        schema_version="fdai.lifecycle-native-scope.v1",
        installation_id="installation-alpha",
        entity_id="application",
        product="example-web",
        scope_digest=scope().digest,
        approval_digest="sha256:" + "b" * 64,
        creation_receipt_digest="sha256:" + "c" * 64,
    )
    proof = sign_native_scope(claim, key)
    public = key.public_key().public_bytes_raw()
    assert proof.verify(public)
    assert not proof.verify(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
    assert not proof.model_copy(
        update={"claim": claim.model_copy(update={"installation_id": "another"})}
    ).verify(public)
    with pytest.raises(ValidationError):
        type(proof).model_validate_json(proof.model_dump_json().replace(proof.signature, "!" * 88))
