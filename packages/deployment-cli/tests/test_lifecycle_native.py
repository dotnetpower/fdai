from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
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


def test_empty_scheduled_scope_preserves_existing_canonical_bytes_and_digest():
    original = scope()
    legacy = {
        "installation_id": "installation-alpha",
        "entity_id": "application",
        "product": "example-web",
        "namespace": "example-test",
        "components": ["frontend"],
    }
    assert canonical_bytes(original.model_dump(mode="json")) == canonical_bytes(legacy)
    assert original.digest == "sha256:" + canonical_digest(legacy)
    assert scope(scheduled_components=()).digest == original.digest


def test_scheduled_scope_explicitly_binds_only_named_cronjobs():
    original = scope()
    scheduled = scope(scheduled_components=("analyzer",))
    assert scheduled.resources == original.resources | {("CronJob", "analyzer")}
    assert scheduled.digest != original.digest
    assert scheduled.model_dump(mode="json")["scheduled_components"] == ["analyzer"]


def test_workers_need_no_placeholder_service_or_different_execution_path():
    original = scope()
    worker = scope(service_components=())
    assert worker.resources == frozenset({("Deployment", "frontend")})
    assert worker.digest != original.digest
    assert worker.model_dump(mode="json")["service_components"] == []
    with pytest.raises(ValidationError):
        scope(service_components=("other",))


@pytest.mark.parametrize(
    "scheduled",
    [("b", "a"), ("a", "a"), ("frontend",), ("invalid.name",)],
)
def test_scheduled_scope_rejects_ambiguous_or_overlapping_resources(scheduled):
    with pytest.raises(ValidationError):
        scope(scheduled_components=scheduled)


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
