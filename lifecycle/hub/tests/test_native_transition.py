from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_enrollment import installation_key_id
from fdai_deployment_cli.lifecycle_native_transition import (
    NativeScopeTransitionRequest,
    SignedNativeScopeTransitionApproval,
    sign_transition_request,
)
from lifecycle.hub.tests.configuration_key_helpers import (
    recovery_for,
    remote_auth,
    tokens,
)
from lifecycle.hub.tests.test_native_ownership import acceptance
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from fdai_lifecycle_hub import audit, models
from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.configuration_key_store import ConfigurationKeyStore
from fdai_lifecycle_hub.domain import Issued, NoEligibleRelease
from fdai_lifecycle_hub.execution_settings import ApplicationBindingRequest
from fdai_lifecycle_hub.migrations import require_schema
from fdai_lifecycle_hub.native_ownership import NativeOwnershipStore
from fdai_lifecycle_hub.native_transition import NativeTransitionError, NativeTransitionStore
from fdai_lifecycle_hub.remote_auth import DevelopmentRecoveryAuthorization
from fdai_lifecycle_hub.signing import raw_public_key


@pytest.fixture
def native_store(hub_store, enroll, installation, now, monkeypatch, capsys):
    from fdai_lifecycle_hub import cli

    monkeypatch.setattr(cli, "_store", lambda: hub_store)
    assert cli.main(["migrate"]) == 0
    capsys.readouterr()
    require_schema(hub_store.engine, "lifecycle_hub")
    enroll(hub_store, installation)
    identifier = installation.installation_id
    digest = hub_store.execution_settings(identifier)["settings_digest"]
    request = ApplicationBindingRequest(
        request_id=uuid4(),
        expected_settings_digest=digest,
        product="example-app",
        reason_code="operator_application_binding",
        confirmation=f"bind application {identifier} example-app {digest}",
    )
    hub_store.bind_application(identifier, request, operator="owner", now=now)
    return hub_store


def recover(native_store, installation, old_key, replacement, now, *, actor="owner"):
    authorization = DevelopmentRecoveryAuthorization.model_validate(
        {
            "profile": "full-authority-development",
            "installation_id": installation.installation_id,
            "scope": "test-scope",
            "operator_id": actor,
            "previous_identity_key_id": installation_key_id(raw_public_key(old_key)),
            "replacement_identity_public_key": raw_public_key(replacement).hex(),
            "authorized_at": now - timedelta(minutes=1),
            "authorization_expires_at": now + timedelta(days=1),
            "allow_single_owner_configuration_approval": True,
            "reason": "Recover the bounded development installation.",
        }
    )
    recovery, signed = recovery_for(
        replacement,
        now,
        installation_id=installation.installation_id,
        previous_identity_key_id=authorization.previous_identity_key_id,
        scope=authorization.scope,
    )
    ConfigurationKeyStore(native_store.engine).recover_identity(
        installation.installation_id,
        signed,
        actor=actor,
        now=now,
        authorization=authorization,
    )
    return recovery, authorization


def transition_request(
    *,
    installation,
    replacement,
    recovery_digest,
    ownership_digest,
    new_scope_digest,
    now,
):
    values = {
        "schema_version": "fdai.lifecycle-native-transition-request.v1",
        "request_id": uuid4(),
        "installation_id": installation.installation_id,
        "old_entity_id": "core",
        "new_entity_id": "application",
        "old_scope_digest": "sha256:" + "4" * 64,
        "new_scope_digest": new_scope_digest,
        "old_reported_state_digest": installation.reported.digest,
        "ownership_claim_digest": ownership_digest,
        "recovery_request_digest": recovery_digest,
        "recovered_identity_key_id": installation_key_id(raw_public_key(replacement)),
        "existing_resources_digest": "sha256:" + "5" * 64,
        "requested_at": now,
        "expires_at": now + timedelta(minutes=10),
    }
    values["confirmation"] = (
        f"transition native scope {values['installation_id']} "
        f"{values['old_scope_digest']} {values['new_scope_digest']}"
    )
    return sign_transition_request(NativeScopeTransitionRequest(**values), replacement)


def test_hub_approves_only_audited_recovery_and_native_ownership(
    native_store, installation, installation_key, key, planner, now
) -> None:
    replacement = Ed25519PrivateKey.generate()
    recovery, _authorization = recover(
        native_store, installation, installation_key, replacement, now
    )
    ownership = acceptance(native_store, replacement)
    NativeOwnershipStore(native_store).accept(
        installation.installation_id,
        ownership,
        operator="owner",
        now=now,
    )
    signed_request = transition_request(
        installation=installation,
        replacement=replacement,
        recovery_digest=recovery.digest,
        ownership_digest=ownership.proof.claim.digest,
        new_scope_digest=ownership.proof.claim.scope_digest,
        now=now,
    )
    service = NativeTransitionStore(native_store)

    approved = service.approve(
        installation.installation_id,
        signed_request,
        operator="owner",
        now=now + timedelta(minutes=1),
        key=key,
    )

    assert approved.verify(
        raw_public_key(key.private_key),
        key_id=key.key_id,
        key_epoch=key.epoch,
    )
    assert approved.approval.request.request == signed_request.request
    candidate = planner(installation, now)
    assert isinstance(candidate, Issued)
    held = native_store.recompute(
        installation.installation_id,
        lambda _installation, _now: candidate,
        now=now + timedelta(minutes=2),
    )
    assert isinstance(held, NoEligibleRelease)
    assert native_store.current_plan(installation.installation_id, now=now) is None
    assert (
        service.approve(
            installation.installation_id,
            signed_request,
            operator="owner",
            now=now + timedelta(days=1),
            key=key,
        )
        == approved
    )
    with Session(native_store.engine) as session:
        records = session.scalars(
            select(models.AuditRecord).where(
                models.AuditRecord.action == "entity.native_transition_approved"
            )
        ).all()
        assert len(records) == 1
        assert records[0].payload["existing_resources_digest"] == "sha256:" + "5" * 64
        assert audit.chain_intact(session)


@pytest.mark.parametrize("fault", ["proof", "recovery", "ownership", "state", "plan"])
def test_hub_transition_denials_create_no_approval_audit(
    fault, native_store, installation, installation_key, key, planner, now
) -> None:
    replacement = Ed25519PrivateKey.generate()
    recovery, _authorization = recover(
        native_store, installation, installation_key, replacement, now
    )
    ownership = acceptance(native_store, replacement)
    NativeOwnershipStore(native_store).accept(
        installation.installation_id,
        ownership,
        operator="owner",
        now=now,
    )
    signed = transition_request(
        installation=installation,
        replacement=replacement,
        recovery_digest=("sha256:" + "7" * 64 if fault == "recovery" else recovery.digest),
        ownership_digest=(
            "sha256:" + "8" * 64 if fault == "ownership" else ownership.proof.claim.digest
        ),
        new_scope_digest=ownership.proof.claim.scope_digest,
        now=now,
    )
    if fault == "proof":
        signed = sign_transition_request(signed.request, Ed25519PrivateKey.generate())
    if fault == "state":
        changed = signed.request.model_copy(update={"old_reported_state_digest": "9" * 64})
        signed = sign_transition_request(changed, replacement)
    if fault == "plan":
        outcome = planner(installation, now)
        native_store.recompute(
            installation.installation_id,
            lambda _installation, _now: outcome,
            now=now,
        )

    with pytest.raises(NativeTransitionError):
        NativeTransitionStore(native_store).approve(
            installation.installation_id,
            signed,
            operator="owner",
            now=now,
            key=key,
        )

    with Session(native_store.engine) as session:
        assert (
            session.scalar(
                select(models.AuditRecord).where(
                    models.AuditRecord.action == "entity.native_transition_approved"
                )
            )
            is None
        )


def test_authenticated_api_returns_the_hub_signed_transition_approval(
    native_store, installation, installation_key, key, now
) -> None:
    replacement = Ed25519PrivateKey.generate()
    recovery, authorization = recover(
        native_store,
        installation,
        installation_key,
        replacement,
        now,
        actor="requester",
    )
    ownership = acceptance(native_store, replacement)
    NativeOwnershipStore(native_store).accept(
        installation.installation_id,
        ownership,
        operator="owner",
        now=now,
    )
    signed = transition_request(
        installation=installation,
        replacement=replacement,
        recovery_digest=recovery.digest,
        ownership_digest=ownership.proof.claim.digest,
        new_scope_digest=ownership.proof.claim.scope_digest,
        now=now,
    )
    auth = remote_auth(authorization)
    app = create_app(
        native_store,
        clock=lambda: now + timedelta(minutes=1),
        remote_auth=auth,
        transition_key=key,
    )
    token = tokens(app, auth)
    path = f"/v1/installations/{installation.installation_id}/native-transition-approval"

    with TestClient(app, base_url=auth.origin) as client:
        response = client.post(
            path,
            json=signed.model_dump(mode="json"),
            headers=token("requester"),
        )

    assert response.status_code == 200
    approved = SignedNativeScopeTransitionApproval.model_validate_json(response.content)
    assert approved.verify(
        raw_public_key(key.private_key),
        key_id=key.key_id,
        key_epoch=key.epoch,
    )
