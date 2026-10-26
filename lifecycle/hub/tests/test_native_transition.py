from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.lifecycle_enrollment import installation_key_id
from fdai_deployment_cli.lifecycle_native import (
    NativeApproval,
    NativeObjectIdentity,
    NativeOwnershipAcceptance,
    NativeScope,
    NativeScopeClaim,
    sign_native_scope,
)
from fdai_deployment_cli.lifecycle_native_transition import (
    NativeScopeTransitionCompletion,
    NativeScopeTransitionReceipt,
    NativeScopeTransitionReportedState,
    NativeScopeTransitionRequest,
    SignedNativeScopeTransitionApproval,
    existing_resources_digest,
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
from fdai_lifecycle_hub.remote import RemoteConfig, require_bound_agent_principal
from fdai_lifecycle_hub.remote_auth import AgentPrincipal, DevelopmentRecoveryAuthorization
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
    old_entity_id="core",
    new_entity_id="application",
    existing_digest="sha256:" + "5" * 64,
):
    values = {
        "schema_version": "fdai.lifecycle-native-transition-request.v1",
        "request_id": uuid4(),
        "installation_id": installation.installation_id,
        "old_entity_id": old_entity_id,
        "new_entity_id": new_entity_id,
        "old_scope_digest": "sha256:" + "4" * 64,
        "new_scope_digest": new_scope_digest,
        "old_reported_state_digest": installation.reported.digest,
        "ownership_claim_digest": ownership_digest,
        "recovery_request_digest": recovery_digest,
        "recovered_identity_key_id": installation_key_id(raw_public_key(replacement)),
        "existing_resources_digest": existing_digest,
        "requested_at": now,
        "expires_at": now + timedelta(minutes=10),
    }
    values["confirmation"] = (
        f"transition native scope {values['installation_id']} "
        f"{values['old_scope_digest']} {values['new_scope_digest']}"
    )
    return sign_transition_request(NativeScopeTransitionRequest(**values), replacement)


@pytest.fixture
def completion_case(
    hub_store,
    enroll,
    installation,
    installation_key,
    key,
    now,
    monkeypatch,
    capsys,
):
    from fdai_lifecycle_hub import cli

    monkeypatch.setattr(cli, "_store", lambda: hub_store)
    assert cli.main(["migrate"]) == 0
    capsys.readouterr()
    require_schema(hub_store.engine, "lifecycle_hub")
    core = next(entity for entity in installation.entities if entity.entity_id == "core")
    old_entity = replace(core, entity_id="operator-hub-canary")
    old_state = installation.reported.entities["core"]
    live = replace(
        installation,
        entities=frozenset({old_entity}),
        reported=replace(
            installation.reported,
            entities={"operator-hub-canary": old_state},
        ),
    )
    enroll(hub_store, live)
    digest = hub_store.execution_settings(live.installation_id)["settings_digest"]
    binding = ApplicationBindingRequest(
        request_id=uuid4(),
        expected_settings_digest=digest,
        product="example-app",
        reason_code="operator_application_binding",
        confirmation=f"bind application {live.installation_id} example-app {digest}",
    )
    hub_store.bind_application(live.installation_id, binding, operator="owner", now=now)
    replacement = Ed25519PrivateKey.generate()
    recovery, authorization = recover(
        hub_store, live, installation_key, replacement, now, actor="requester"
    )
    components = tuple(f"component-{index:02d}" for index in range(16))
    identities = tuple(
        NativeObjectIdentity(
            kind="Deployment",
            name=component,
            uid=f"uid-existing-{index:02d}",
        )
        for index, component in enumerate(components[:7])
    )
    scope = NativeScope(
        installation_id=live.installation_id,
        entity_id="fdai-workloads",
        product="example-app",
        namespace="fdai-system",
        components=components,
        service_components=(),
    )
    native_approval = NativeApproval(
        schema_version="fdai.lifecycle-native-approval.v1",
        scope=scope,
        profile="full-authority-development",
        approved_by="owner",
        approved_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        existing_resources=identities,
    )
    claim = NativeScopeClaim(
        schema_version="fdai.lifecycle-native-scope.v1",
        installation_id=live.installation_id,
        entity_id=scope.entity_id,
        product=scope.product,
        scope_digest=scope.digest,
        approval_digest=native_approval.digest,
        creation_receipt_digest="sha256:" + "c" * 64,
    )
    ownership = NativeOwnershipAcceptance(
        request_id=uuid4(),
        expected_settings_digest=hub_store.execution_settings(live.installation_id)[
            "settings_digest"
        ],
        proof=sign_native_scope(claim, replacement),
        reason="Approve the exact mixed native workload scope",
        confirmation="",
    )
    ownership = ownership.model_copy(update={"confirmation": ownership.required_confirmation})
    NativeOwnershipStore(hub_store).accept(
        live.installation_id, ownership, operator="owner", now=now
    )
    signed_request = transition_request(
        installation=live,
        replacement=replacement,
        recovery_digest=recovery.digest,
        ownership_digest=claim.digest,
        new_scope_digest=scope.digest,
        now=now,
        old_entity_id=old_entity.entity_id,
        new_entity_id=scope.entity_id,
        existing_digest=existing_resources_digest(
            [item.model_dump(mode="json") for item in identities]
        ),
    )
    signed_approval = NativeTransitionStore(hub_store).approve(
        live.installation_id,
        signed_request,
        operator="requester",
        now=now + timedelta(minutes=1),
        key=key,
    )
    completed_at = now + timedelta(minutes=2)
    state_document = {
        "schema_revision": live.reported.schema_revision,
        "entities": {
            scope.entity_id: {
                "release_id": None,
                "artifact_digests": [],
                "health": "unknown",
            }
        },
        "observed_at": completed_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    if live.reported.available_artifact_digests is not None:
        state_document["available_artifact_digests"] = sorted(
            live.reported.available_artifact_digests
        )
    state = NativeScopeTransitionReportedState.model_validate_json(
        json.dumps({"digest": canonical_digest(state_document), **state_document})
    )
    receipt_document = {
        "schema_version": "fdai.lifecycle-native-transition-receipt.v1",
        "request_digest": signed_request.request.digest,
        "hub_approval_digest": signed_approval.approval.digest,
        "installation_id": live.installation_id,
        "old_entity_id": old_entity.entity_id,
        "new_entity_id": scope.entity_id,
        "old_scope_digest": signed_request.request.old_scope_digest,
        "new_scope_digest": scope.digest,
        "old_reported_state_digest": live.reported.digest,
        "new_reported_state_digest": state.digest,
        "ownership_claim_digest": claim.digest,
        "recovery_request_digest": recovery.digest,
        "existing_resources_digest": signed_request.request.existing_resources_digest,
        "rollback_record_digest": "sha256:" + "d" * 64,
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
    }
    local_receipt = NativeScopeTransitionReceipt.model_validate_json(
        json.dumps(
            {
                **receipt_document,
                "record_digest": "sha256:" + canonical_digest(receipt_document),
            }
        )
    )
    completion = NativeScopeTransitionCompletion(
        schema_version="fdai.lifecycle-native-transition-completion.v1",
        approval=signed_approval,
        transition_receipt=local_receipt,
        native_approval=native_approval,
        reported_state=state,
    )
    return SimpleNamespace(
        store=hub_store,
        installation=live,
        replacement=replacement,
        authorization=authorization,
        completion=completion,
        key=key,
        now=now,
    )


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


def test_completion_atomically_moves_live_shape_and_returns_exact_retry(
    completion_case,
) -> None:
    case = completion_case
    service = NativeTransitionStore(case.store)

    receipt = service.complete(
        case.installation.installation_id,
        case.completion,
        principal="agent-executor",
        now=case.now + timedelta(minutes=3),
        key=case.key,
    )

    installation = case.store.load(case.installation.installation_id)
    assert installation.managed_entity_ids == frozenset({"fdai-workloads"})
    assert set(installation.reported.entities) == {"fdai-workloads"}
    assert installation.reported.entities["fdai-workloads"].release_id is None
    assert receipt.old_entity_id == "operator-hub-canary"
    assert receipt.new_entity_id == "fdai-workloads"
    assert (
        receipt.authoritative_uids_digest
        == case.completion.transition_receipt.existing_resources_digest
    )
    assert (
        service.complete(
            case.installation.installation_id,
            case.completion,
            principal="agent-executor",
            now=case.now + timedelta(minutes=4),
            key=case.key,
        )
        == receipt
    )
    with Session(case.store.engine) as session:
        old = session.get(
            models.Entity,
            (case.installation.installation_id, "operator-hub-canary"),
        )
        new = session.get(
            models.Entity,
            (case.installation.installation_id, "fdai-workloads"),
        )
        assert old is not None and old.settings is None
        assert new is not None and new.settings is not None
        records = session.scalars(
            select(models.AuditRecord).where(
                models.AuditRecord.action == "entity.native_transition_completed"
            )
        ).all()
        assert len(records) == 1
        assert audit.chain_intact(session)


def test_trusted_cli_completes_the_same_atomic_transition(
    completion_case,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    from fdai_lifecycle_hub import cli, domain

    case = completion_case
    command_path = tmp_path / "native-transition-completion.json"
    command_path.write_text(case.completion.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(cli, "_store", lambda: case.store)
    monkeypatch.setattr(cli, "_native_transition_key", lambda _args: case.key)
    monkeypatch.setattr(domain, "utc_now", lambda: case.now + timedelta(minutes=3))

    result = cli.main(
        [
            "complete-native-transition",
            case.installation.installation_id,
            str(command_path),
            "--agent-principal",
            "agent-executor",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert result == 0
    assert output["new_entity_id"] == "fdai-workloads"
    assert output["receipt_digest"].startswith("sha256:")


@pytest.mark.parametrize("fault", ["receipt", "uid", "plan"])
def test_completion_rejects_wrong_receipt_uid_or_open_plan(
    fault,
    completion_case,
) -> None:
    case = completion_case
    command = case.completion
    if fault == "receipt":
        command = command.model_copy(
            update={
                "transition_receipt": command.transition_receipt.model_copy(
                    update={"new_scope_digest": "sha256:" + "f" * 64}
                )
            }
        )
    elif fault == "uid":
        identities = list(command.native_approval.existing_resources)
        identities[0] = identities[0].model_copy(update={"uid": "uid-replaced"})
        command = command.model_copy(
            update={
                "native_approval": command.native_approval.model_copy(
                    update={"existing_resources": tuple(identities)}
                )
            }
        )
    else:
        with Session(case.store.engine) as session, session.begin():
            session.add(
                models.Plan(
                    plan_id="transition-blocking-plan",
                    installation_id=case.installation.installation_id,
                    sequence=999,
                    plan_type="upgrade",
                    target_release_id="1.6.0",
                    source_state_digest=case.installation.reported.digest,
                    configuration_digest=case.installation.configuration.digest,
                    hub_key_id=case.key.key_id,
                    entity_ids=["operator-hub-canary"],
                    signed_payload=b"test-plan",
                    signature=b"test-signature",
                    issued_at=case.now,
                    expires_at=case.now + timedelta(minutes=10),
                )
            )

    with pytest.raises(NativeTransitionError):
        NativeTransitionStore(case.store).complete(
            case.installation.installation_id,
            command,
            principal="agent-executor",
            now=case.now + timedelta(minutes=3),
            key=case.key,
        )

    unchanged = case.store.load(case.installation.installation_id)
    assert unchanged.managed_entity_ids == frozenset({"operator-hub-canary"})
    assert set(unchanged.reported.entities) == {"operator-hub-canary"}


@pytest.mark.parametrize(
    "stage",
    ["source-unmanaged", "state-recorded", "target-managed", "audit-appended"],
)
def test_completion_interruption_rolls_back_every_hub_write(stage, completion_case) -> None:
    case = completion_case

    def interrupt(current: str) -> None:
        if current == stage:
            raise RuntimeError("simulated interruption")

    with pytest.raises(RuntimeError, match="simulated interruption"):
        NativeTransitionStore(case.store).complete(
            case.installation.installation_id,
            case.completion,
            principal="agent-executor",
            now=case.now + timedelta(minutes=3),
            key=case.key,
            after_write=interrupt,
        )

    unchanged = case.store.load(case.installation.installation_id)
    assert unchanged.managed_entity_ids == frozenset({"operator-hub-canary"})
    assert set(unchanged.reported.entities) == {"operator-hub-canary"}
    with Session(case.store.engine) as session:
        assert (
            session.scalar(
                select(models.AuditRecord).where(
                    models.AuditRecord.action == "entity.native_transition_completed"
                )
            )
            is None
        )


def test_authenticated_agent_completion_rejects_wrong_execution_identity(
    completion_case,
) -> None:
    case = completion_case
    auth = remote_auth(case.authorization).model_copy(
        update={
            "agent_principals": (
                AgentPrincipal(
                    installation_id=case.installation.installation_id,
                    object_id="agent-executor",
                    client_id="agent-client",
                ),
            )
        }
    )
    app = create_app(
        case.store,
        clock=lambda: case.now + timedelta(minutes=3),
        remote_auth=auth,
        transition_key=case.key,
    )
    token = tokens(app, auth)
    path = f"/v1/installations/{case.installation.installation_id}/native-transition-completion"
    body = case.completion.model_dump(mode="json")

    with TestClient(app, base_url=auth.origin) as client:
        wrong = client.post(
            path,
            json=body,
            headers=token(
                "other-agent",
                azp="agent-client",
                roles=["Agent.Access"],
                omit=("scp",),
            ),
        )
        accepted = client.post(
            path,
            json=body,
            headers=token(
                "agent-executor",
                azp="agent-client",
                roles=["Agent.Access"],
                omit=("scp",),
            ),
        )

    assert wrong.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json()["new_entity_id"] == "fdai-workloads"


def test_remote_completion_requires_configured_agent_principal(completion_case) -> None:
    case = completion_case
    auth = remote_auth(case.authorization).model_copy(
        update={
            "agent_principals": (
                AgentPrincipal(
                    installation_id=case.installation.installation_id,
                    object_id="agent-executor",
                    client_id="agent-client",
                ),
            )
        }
    )
    config = RemoteConfig(kind="target", auth=auth, origin=auth.origin)

    require_bound_agent_principal(
        config,
        case.installation.installation_id,
        "agent-executor",
    )
    with pytest.raises(ValueError, match="bound Agent principal"):
        require_bound_agent_principal(
            config,
            case.installation.installation_id,
            "other-agent",
        )


@pytest.mark.integration
def test_exact_concurrent_completion_returns_one_receipt(completion_case) -> None:
    case = completion_case
    if case.store.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock concurrency test")
    barrier = Barrier(2)

    def complete():
        barrier.wait()
        return NativeTransitionStore(case.store).complete(
            case.installation.installation_id,
            case.completion,
            principal="agent-executor",
            now=case.now + timedelta(minutes=3),
            key=case.key,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = tuple(executor.map(lambda _index: complete(), range(2)))

    assert receipts[0] == receipts[1]
    with Session(case.store.engine) as session:
        assert (
            len(
                session.scalars(
                    select(models.AuditRecord).where(
                        models.AuditRecord.action == "entity.native_transition_completed"
                    )
                ).all()
            )
            == 1
        )
