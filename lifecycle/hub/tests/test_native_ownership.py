from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_native import (
    NativeOwnershipAcceptance,
    NativeScopeClaim,
    sign_native_scope,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from fdai_lifecycle_hub import audit, models
from fdai_lifecycle_hub.domain import EntityState, Health, Issued
from fdai_lifecycle_hub.entity import EntitySettings, OwnershipEvidence
from fdai_lifecycle_hub.errors import EntityNotReportedError, EntitySettingsRejectedError
from fdai_lifecycle_hub.execution_settings import ApplicationBindingRequest
from fdai_lifecycle_hub.migrations import _versions, migrate, require_schema
from fdai_lifecycle_hub.native_ownership import (
    NATIVE_ENTITY_KIND,
    NativeOwnershipError,
    NativeOwnershipStore,
)
from fdai_lifecycle_hub.store import HubStore


@pytest.fixture
def native_store(hub_store, enroll, installation, now):
    migrate(hub_store.engine, "lifecycle_hub", models.Base.metadata.create_all)
    enroll(hub_store, installation)
    identifier = installation.installation_id
    digest = hub_store.execution_settings(identifier)["settings_digest"]
    request = ApplicationBindingRequest.model_validate_json(
        json.dumps(
            {
                "request_id": str(uuid4()),
                "expected_settings_digest": digest,
                "product": "example-app",
                "reason_code": "operator_application_binding",
                "confirmation": f"bind application {identifier} example-app {digest}",
            }
        )
    )
    hub_store.bind_application(identifier, request, operator="owner", now=now)
    return hub_store


def acceptance(store, key, *, entity_id="application", product="example-app"):
    claim = NativeScopeClaim(
        schema_version="fdai.lifecycle-native-scope.v1",
        installation_id="installation-alpha",
        entity_id=entity_id,
        product=product,
        scope_digest="sha256:" + "a" * 64,
        approval_digest="sha256:" + "b" * 64,
        creation_receipt_digest="sha256:" + "c" * 64,
    )
    command = NativeOwnershipAcceptance(
        request_id=uuid4(),
        expected_settings_digest=store.execution_settings("installation-alpha")["settings_digest"],
        proof=sign_native_scope(claim, key),
        reason="Approve the independently created workload scope",
        confirmation="",
    )
    return command.model_copy(update={"confirmation": command.required_confirmation})


def test_acceptance_registers_only_unmanaged_scope_and_audits_once(
    native_store, installation_key, now
):
    store = native_store
    command = acceptance(store, installation_key)
    result = NativeOwnershipStore(store).accept(
        "installation-alpha", command, operator="owner", now=now
    )
    assert result["changed"] is True
    with Session(store.engine) as session:
        entity = session.scalars(
            select(models.Entity).where(models.Entity.entity_id == "application")
        ).one()
        assert entity.kind == NATIVE_ENTITY_KIND
        assert entity.settings is None
        assert entity.ownership["native_creation_receipt_digest"] == command.proof.claim.digest
        assert (
            session.scalar(
                select(models.EntityReportedState).where(
                    models.EntityReportedState.entity_id == "application"
                )
            )
            is None
        )
        records = session.scalars(
            select(models.AuditRecord).where(
                models.AuditRecord.action == "entity.native_creation_accepted"
            )
        ).all()
        assert len(records) == 1
        assert records[0].payload["operator"] == "owner"
        assert audit.chain_intact(session)
    restarted = NativeOwnershipStore(HubStore(store.engine))
    assert restarted.accept(
        "installation-alpha", command, operator="owner", now=now + timedelta(minutes=1)
    ) == {"changed": False, "claim_digest": command.proof.claim.digest}
    with pytest.raises(NativeOwnershipError, match="already_bound"):
        restarted.accept(
            "installation-alpha",
            command.model_copy(update={"request_id": uuid4()}),
            operator="owner",
            now=now,
        )


@pytest.mark.parametrize("change", ["signature", "product", "confirmation", "settings", "entity"])
def test_invalid_acceptance_preserves_entities_and_audit(
    native_store, installation_key, now, change
):
    store = native_store
    key = Ed25519PrivateKey.generate() if change == "signature" else installation_key
    command = acceptance(
        store,
        key,
        entity_id="console" if change == "entity" else "application",
        product="foreign-app" if change == "product" else "example-app",
    )
    if change == "confirmation":
        command = command.model_copy(update={"confirmation": "accept"})
    if change == "settings":
        command = command.model_copy(update={"expected_settings_digest": "f" * 64})
    with Session(store.engine) as session:
        before = session.scalars(select(models.AuditRecord.record_hash)).all()
        count = len(session.scalars(select(models.Entity)).all())
    with pytest.raises(NativeOwnershipError):
        NativeOwnershipStore(store).accept("installation-alpha", command, operator="owner", now=now)
    with Session(store.engine) as session:
        assert session.scalars(select(models.AuditRecord.record_hash)).all() == before
        assert len(session.scalars(select(models.Entity)).all()) == count


def test_request_uuid_cannot_be_reused_by_another_actor_or_command(
    native_store, installation_key, now
):
    command = acceptance(native_store, installation_key)
    service = NativeOwnershipStore(native_store)
    service.accept("installation-alpha", command, operator="owner", now=now)
    for changed, operator in (
        (command, "other"),
        (command.model_copy(update={"reason": "changed"}), "owner"),
    ):
        with pytest.raises(NativeOwnershipError, match="request_conflict"):
            service.accept("installation-alpha", changed, operator=operator, now=now)


def test_generic_ownership_cannot_inject_native_evidence(native_store, now):
    evidence = OwnershipEvidence(native_creation_receipt_digest="sha256:" + "a" * 64)
    with pytest.raises(ValueError, match="separate verified operator acceptance"):
        native_store.record_ownership(
            "installation-alpha", "console", evidence, operator="owner", now=now
        )


def test_trusted_cli_uses_verified_acceptance_without_printing_proof(
    native_store, installation_key, now, tmp_path, monkeypatch, capsys
):
    from fdai_lifecycle_hub import cli, domain

    request = acceptance(native_store, installation_key)
    path = tmp_path / "acceptance.json"
    path.write_text(request.model_dump_json())
    monkeypatch.setattr(cli, "_store", lambda: native_store)
    monkeypatch.setattr(domain, "utc_now", lambda: now)
    arguments = ["accept-native-ownership", "installation-alpha", str(path), "--operator", "owner"]
    assert cli.main(arguments) == 0
    assert json.loads(capsys.readouterr().out) == {"accepted": True, "changed": True}
    path.write_text('{"reason":"private-input-marker"}')
    assert cli.main(arguments) == 1
    output = capsys.readouterr()
    assert "private-input-marker" not in output.out + output.err
    assert request.proof.signature not in output.out + output.err


def test_open_plan_blocks_acceptance_without_withdrawing_the_plan(
    native_store, installation_key, installation, planner, now
):
    outcome = planner(installation, now)
    assert isinstance(outcome, Issued)
    native_store.recompute(
        installation.installation_id, lambda _installation, _now: outcome, now=now
    )
    before = native_store.load(installation.installation_id)
    command = acceptance(native_store, installation_key)
    with pytest.raises(NativeOwnershipError, match="plan_pending"):
        NativeOwnershipStore(native_store).accept(
            installation.installation_id, command, operator="owner", now=now
        )
    assert native_store.load(installation.installation_id) == before


def test_registration_requires_real_empty_report_before_normal_manage(
    native_store, installation_key, now
):
    store = native_store
    command = acceptance(store, installation_key)
    NativeOwnershipStore(store).accept("installation-alpha", command, operator="owner", now=now)
    overrides = EntitySettings(overrides=({"versions": ">=0.0.0", "values": {}},))
    with pytest.raises(EntityNotReportedError):
        store.manage(
            "installation-alpha",
            "application",
            overrides,
            operator="owner",
            now=now,
            initial_release="0.0.0",
        )
    reported = store.load("installation-alpha").reported
    empty = EntityState(release_id=None, artifact_digests=frozenset(), health=Health.UNKNOWN)
    snapshot = replace(
        reported,
        digest="d" * 64,
        observed_at=now,
        entities={**reported.entities, "application": empty},
    )
    store.record_state("installation-alpha", snapshot, now=now)
    with pytest.raises(EntitySettingsRejectedError, match="initial_release_required"):
        store.manage("installation-alpha", "application", overrides, operator="owner", now=now)
    assert (
        store.manage(
            "installation-alpha",
            "application",
            overrides,
            operator="owner",
            now=now,
            initial_release="0.0.0",
        )
        == ">=0.0.0"
    )
    assert "application" in store.load("installation-alpha").managed_entity_ids


def test_revision_five_requires_explicit_marker_upgrade_without_changing_data(
    native_store, installation_key, now
):
    store = native_store
    command = acceptance(store, installation_key)
    versions = _versions("lifecycle_hub")
    with store.engine.begin() as connection:
        connection.execute(versions.update().values(revision=5))
    with pytest.raises(ValueError, match="Unsupported Hub schema revision"):
        require_schema(store.engine, "lifecycle_hub")
    with pytest.raises(ValueError, match="Unsupported Hub schema revision"):
        NativeOwnershipStore(store).accept("installation-alpha", command, operator="owner", now=now)
    with Session(store.engine) as session:
        before = [
            (row.entity_id, row.ownership, row.settings)
            for row in session.scalars(select(models.Entity))
        ]
        hashes = session.scalars(select(models.AuditRecord.record_hash)).all()
    migrate(store.engine, "lifecycle_hub", models.Base.metadata.create_all)
    require_schema(store.engine, "lifecycle_hub")
    with Session(store.engine) as session:
        assert [
            (row.entity_id, row.ownership, row.settings)
            for row in session.scalars(select(models.Entity))
        ] == before
        assert session.scalars(select(models.AuditRecord.record_hash)).all() == hashes
    assert (
        NativeOwnershipStore(store).accept(
            "installation-alpha", command, operator="owner", now=now
        )["changed"]
        is True
    )
