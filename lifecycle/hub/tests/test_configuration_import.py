from __future__ import annotations

from base64 import b64decode
from dataclasses import replace
from datetime import timedelta
from functools import partial

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fdai_deployment_cli.lifecycle_configuration_package import (
    SignedConfigurationPackage,
    decrypt_installation_configuration_identifiers,
)
from lifecycle.hub.tests.configuration_import_helpers import make_harness
from lifecycle.hub.tests.configuration_key_helpers import recovery_for
from lifecycle.hub.tests.test_configuration_revision import plan_case as plan_case
from lifecycle.hub.tests.test_remote_catalog import approve
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from fdai_lifecycle_hub import audit, models
from fdai_lifecycle_hub.agent_artifacts import artifact_for_plan
from fdai_lifecycle_hub.configuration_import_models import (
    ConfigurationHead,
    ConfigurationImport,
    ConfigurationPlanImport,
)
from fdai_lifecycle_hub.configuration_import_store import ConfigurationImportStore
from fdai_lifecycle_hub.configuration_keys import KeyBindingError
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.remote_auth import DevelopmentRecoveryAuthorization
from fdai_lifecycle_hub.signing import installation_key_id, raw_public_key
from fdai_lifecycle_hub.store import HubStore
from fdai_release_hub.store import Change, ReleaseStore


@pytest.fixture
def imported(tmp_path, plan_case, installation_key, key, now, sign, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'import.db'}")
    harness = make_harness(
        engine, plan_case, installation_key, key, now, sign, tmp_path, monkeypatch
    )
    try:
        with harness.client:
            harness.register_keys()
            yield harness
    finally:
        engine.dispose()


def test_recovered_development_owner_can_approve_first_configuration(
    tmp_path, plan_case, installation_key, key, now, sign, monkeypatch
):
    replacement = Ed25519PrivateKey.generate()
    authorization = DevelopmentRecoveryAuthorization.model_validate(
        {
            "profile": "full-authority-development",
            "installation_id": plan_case.installation.installation_id,
            "scope": "rg-fdai-dev-wus3",
            "operator_id": "requester",
            "previous_identity_key_id": installation_key_id(raw_public_key(installation_key)),
            "replacement_identity_public_key": raw_public_key(replacement).hex(),
            "authorized_at": now - timedelta(minutes=1),
            "authorization_expires_at": now + timedelta(days=14) - timedelta(minutes=1),
            "allow_single_owner_configuration_approval": True,
            "reason": "Complete the exact recovered development configuration.",
        }
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'single-owner-import.db'}")
    harness = make_harness(
        engine,
        plan_case,
        installation_key,
        key,
        now,
        sign,
        tmp_path,
        monkeypatch,
        recovery=authorization,
    )
    try:
        with harness.client:
            request, signed = recovery_for(
                replacement,
                harness.now,
                installation_id=harness.iid,
                previous_identity_key_id=authorization.previous_identity_key_id,
            )
            response = harness.post("configuration-keys/recover-identity", signed)
            assert response.status_code == 202, response.json()
            assert response.json()["request_digest"] == request.digest
            harness.identity = replacement
            harness.register_keys(approver="requester")
            scope, signed_scope = harness.scope_request()
            assert harness.post("configuration-scope/request", signed_scope).status_code == 202
            assert (
                harness.post(
                    "configuration-scope/approve",
                    {"digest": scope.digest},
                    actor="requester",
                ).status_code
                == 202
            )
            harness.scope_digest = scope.digest
            decision = harness.stage()
            harness.activate(decision, approver="requester")
            assert (
                ConfigurationImportStore(engine).read(harness.iid)["active_digest"]
                == decision["digest"]
            )
            recompute = harness.post("recompute", {})
            assert recompute.status_code == 200, recompute.json()
            assert recompute.json()["outcome"] == "issued"
    finally:
        engine.dispose()


def test_real_jwt_scope_stage_approval_activation_default_consumer_and_privacy(
    imported, monkeypatch
):
    h = imported
    root = f"/v1/installations/{h.iid}"
    signed = h.import_request()
    assert (
        h.client.post(root + "/configuration/import", json=signed.model_dump()).status_code == 401
    )
    assert (
        h.post("configuration/import", signed).json()["error"] == "configuration_scope_unapproved"
    )
    scope = h.approve_scope()
    signed = h.import_request()
    original = b64decode(signed.signed_container)
    with monkeypatch.context() as patch:
        patch.setattr(
            "fdai_deployment_cli.lifecycle_configuration_package.open_identifiers",
            lambda *args, **kwargs: pytest.fail("Hub must never decrypt identifiers"),
        )
        decision = h.stage(signed)
        assert h.post("recompute", {}).json()["error"] == "configuration_not_activated"
        assert h.post("configuration/activate", decision).status_code == 409
        assert h.post("configuration/approve", decision).status_code == 409
        h.activate(decision)
        outcome = h.post("recompute", {})
        assert outcome.status_code == 200, outcome.json()
        assert outcome.json()["outcome"] == "issued", outcome.json()
    with Session(h.engine) as session:
        row = session.get(ConfigurationImport, decision["digest"])
        assert row.container == original
        assert row.binding_version == 1
        assert row.scope_digest == scope.digest
        assert b"private-identifier" not in row.container + row.context
        assert audit.chain_intact(session)
    plan = h.store.current_plan(h.iid, now=h.now)
    assert plan.configuration_digest == decision["digest"]
    assert plan.entity_ids == frozenset({"core", "console"})
    value = decrypt_installation_configuration_identifiers(
        h.case.candidate.package,
        entity_id="1" * 64,
        configuration_key=h.case.signing.public_key(),
        installation_key=h.case.recipient,
        configuration_schema=h.case.source.configuration_schema,
        sealed_keys=h.case.source.sealed_keys,
        entity_ids=frozenset(dict(h.case.candidate.entity_bindings).values()),
        release_version="1.6.0",
        release_digest=h.case.source.release_digest,
    )
    assert value == {"endpoint": "https://example.com/private-identifier"}
    h.now += timedelta(minutes=6)
    assert h.stage(signed) == decision
    restarted_engine = create_engine(h.engine.url)
    try:
        restarted = ConfigurationImportStore(restarted_engine)
        assert b64decode(restarted.read(h.iid, decision["digest"])["signed_container"]) == original
        assert (
            restarted.import_revision(
                h.iid, signed, actor="requester", now=h.now, catalog=h.case.catalog
            )
            == decision
        )
        assert (
            HubStore(restarted_engine).current_plan(h.iid, now=h.now).configuration_digest
            == decision["digest"]
        )
    finally:
        restarted_engine.dispose()
    with Session(h.engine) as session:
        assert session.scalar(select(func.count()).select_from(ConfigurationImport)) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"entity_bindings": {"core": "1" * 64}},
        {"entity_bindings": {"core": "1" * 64, "foreign": "2" * 64}},
        {"release_digest": "0" * 64},
        {"schema_digest": "0" * 64},
        {"installation_id": "another-installation"},
    ],
)
def test_scope_cannot_create_entity_installation_or_release_authority(imported, change):
    h = imported
    scope, signed = h.scope_request(**change)
    result = h.post("configuration-scope/request", signed)
    assert result.status_code == 409
    assert (
        h.post(
            "configuration-scope/approve", {"digest": scope.digest}, actor="approver"
        ).status_code
        == 409
    )
    assert h.post("configuration/import", h.import_request()).status_code == 409


def test_scope_requires_independent_exact_approval_and_installation_proof(imported):
    h = imported
    scope, signed = h.scope_request()
    forged = signed.model_copy(update={"identity_proof": h.import_request().identity_proof})
    assert h.post("configuration-scope/request", forged).status_code == 409
    assert h.post("configuration-scope/request", signed).status_code == 202
    assert h.post("configuration-scope/approve", {"digest": scope.digest}).status_code == 409
    h.now += timedelta(minutes=11)
    assert (
        h.post(
            "configuration-scope/approve", {"digest": scope.digest}, actor="approver"
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "mutation", ["payload", "signature", "installation", "version", "scope", "predecessor"]
)
def test_tamper_and_context_substitution_are_rejected_without_head(imported, mutation):
    h = imported
    h.approve_scope()
    package = h.case.candidate.package
    if mutation == "payload":
        package = SignedConfigurationPackage(package.payload + b" ", package.signature)
    elif mutation == "signature":
        package = SignedConfigurationPackage(package.payload, b"0" * 64)
    changes = {
        "installation": {"installation_id": "another-installation"},
        "version": {"version": 2},
        "scope": {"scope_digest": "0" * 64},
        "predecessor": {"predecessor": "0" * 64},
    }.get(mutation, {})
    response = h.post("configuration/import", h.import_request(package, **changes))
    assert response.status_code == 409, response.json()
    with Session(h.engine) as session:
        assert session.get(ConfigurationHead, h.iid) is None
        assert session.scalar(select(func.count()).select_from(ConfigurationImport)) == 0
        assert audit.chain_intact(session)
    assert "private-identifier" not in response.text


def test_old_revision_fork_retry_bytes_and_activation_cas(imported):
    h = imported
    h.approve_scope()
    original = h.import_request()
    first = h.stage(original)
    child = h.child("b")
    second = h.stage(h.import_request(child, predecessor=first["digest"]))
    assert h.post("configuration/import", original).json()["error"] == "configuration_old_revision"
    assert h.post("configuration/approve", first, actor="approver").status_code == 409
    assert h.post("configuration/activate", first).status_code == 409
    competing = h.child("c")
    assert (
        h.post(
            "configuration/import", h.import_request(competing, predecessor=first["digest"])
        ).status_code
        == 409
    )
    h.activate(second)
    assert h.post("recompute", {}).json()["outcome"] == "issued"
    ancestor = artifact_for_plan(
        h.store,
        h.catalog,
        h.iid,
        "configuration",
        first["digest"],
        now=h.now,
    )
    assert ancestor.payload == h.case.candidate.package.payload
    with pytest.raises(KeyBindingError, match="configuration_revision_missing"):
        artifact_for_plan(
            h.store,
            h.catalog,
            h.iid,
            "configuration",
            "f" * 64,
            now=h.now,
        )
    retry = h.import_request(child, predecessor=first["digest"])
    assert h.post("configuration/import", retry).json()["error"] == "configuration_retry_conflict"


def test_cross_key_history_is_verified_with_exact_accepted_versions(imported):
    h = imported
    h.approve_scope()
    first = h.stage()
    h.activate(first)
    with Session(h.engine) as session:
        first_key = session.get(models.ConfigurationKeyBinding, (h.iid, 1)).request_digest
    signer, recipient = Ed25519PrivateKey.generate(), X25519PrivateKey.generate()
    h.register_keys(signer=signer, recipient=recipient, version=2, predecessor=first_key)
    package = h.child("b", signer=signer, recipient=recipient, bindings=(h.history_binding(),))
    second = h.stage(h.import_request(package, version=2, predecessor=first["digest"]))
    h.activate(second)
    outcome = h.post("recompute", {})
    assert outcome.json()["outcome"] == "issued", outcome.json()
    assert h.store.current_plan(h.iid, now=h.now).configuration_digest == package.digest
    with Session(h.engine) as session, session.begin():
        session.get(models.ConfigurationKeyBinding, (h.iid, 1)).revoked_at = h.now
    response = h.post("recompute", {})
    assert response.status_code == 409
    assert response.json()["error"] == "configuration_history_binding_unavailable"
    assert h.store.current_plan(h.iid, now=h.now) is None


@pytest.mark.parametrize(
    "tamper", ["container", "receipt", "binding", "missing-proof", "plan-pin", "key-pin", "head"]
)
def test_persisted_tamper_or_unprovable_history_holds_default_consumer(imported, tamper):
    h = imported
    h.approve_scope()
    decision = h.stage()
    h.activate(decision)
    assert h.post("recompute", {}).json()["outcome"] == "issued"
    plan = h.store.current_plan(h.iid, now=h.now)
    with Session(h.engine) as session, session.begin():
        row = session.get(ConfigurationImport, decision["digest"])
        if tamper == "container":
            row.container += b" "
        elif tamper == "receipt":
            row.receipt_digest = "0" * 64
        elif tamper == "binding":
            row.binding_digest = "0" * 64
        elif tamper == "missing-proof":
            row.identity_proof = b"0" * 64
        elif tamper == "plan-pin":
            session.delete(session.get(ConfigurationPlanImport, plan.plan_id))
        elif tamper == "key-pin":
            session.delete(session.get(models.ConfigurationPlanTrust, plan.plan_id))
        else:
            session.delete(session.get(ConfigurationHead, h.iid))
    assert h.store.current_plan(h.iid, now=h.now) is None
    assert h.post("recompute", {}).status_code == 409
    assert h.store.current_plan(h.iid, now=h.now) is None


def test_import_transaction_rolls_back_head_revision_and_audit_together(imported, monkeypatch):
    h = imported
    h.approve_scope()
    first = h.stage()
    child = h.child("b")
    signed = h.import_request(child, predecessor=first["digest"])
    before = ConfigurationImportStore(h.engine).read(h.iid)
    with Session(h.engine) as session:
        audit_count = session.scalar(select(func.count()).select_from(models.AuditRecord))

    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    with monkeypatch.context() as patch:
        patch.setattr("fdai_lifecycle_hub.configuration_import_store.audit.append", unavailable)
        with pytest.raises(RuntimeError, match="synthetic"):
            ConfigurationImportStore(h.engine).import_revision(
                h.iid, signed, actor="requester", now=h.now, catalog=h.case.catalog
            )
    assert ConfigurationImportStore(h.engine).read(h.iid) == before
    with Session(h.engine) as session:
        assert session.get(ConfigurationImport, child.digest) is None
        assert session.scalar(select(func.count()).select_from(models.AuditRecord)) == audit_count
    assert h.stage(signed)["digest"] == child.digest


@pytest.mark.parametrize("trust", ["missing", "revoked", "expired", "approval-unprovable"])
def test_current_trust_absence_revocation_expiry_or_unprovable_approval_holds(imported, trust):
    h = imported
    h.approve_scope()
    if trust == "expired":
        h.now += timedelta(days=2)
    else:
        with Session(h.engine) as session, session.begin():
            binding = session.get(models.ConfigurationKeyBinding, (h.iid, 1))
            if trust == "missing":
                session.delete(binding)
            elif trust == "revoked":
                binding.revoked_at = h.now
            else:
                binding.approved_by = "unproven-approver"
    response = h.post("configuration/import", h.import_request())
    assert response.status_code == 409, response.json()
    with Session(h.engine) as session:
        assert session.get(ConfigurationHead, h.iid) is None
        assert audit.chain_intact(session)


def test_absent_configuration_and_staged_change_do_not_withdraw_unrelated_legacy_plan(
    imported, catalog
):
    h = imported
    legacy = replace(catalog, channels={"DEV": frozenset(catalog.releases)})
    outcome = h.store.recompute(h.iid, partial(plan_next, catalog=legacy, key=h.key), now=h.now)
    before = h.store.current_plan(h.iid, now=h.now)
    assert before.plan_id == outcome.plan.plan_id
    assert ConfigurationImportStore(h.engine).read(h.iid)["accepted_digest"] is None
    h.approve_scope()
    h.stage()
    assert h.post("recompute", {}).json()["error"] == "configuration_not_activated"
    assert h.store.current_plan(h.iid, now=h.now).plan_id == before.plan_id


def test_activated_configuration_never_schedules_same_release_action(imported):
    h = imported
    h.approve_scope()
    decision = h.stage()
    h.activate(decision)
    installation = h.store.load(h.iid)
    state = replace(
        installation.reported,
        digest="e" * 64,
        observed_at=h.now,
        entities={
            entity_id: replace(value, release_id="1.6.0")
            for entity_id, value in installation.reported.entities.items()
        },
    )
    h.store.record_state(h.iid, state, now=h.now)
    assert h.post("recompute", {}).json()["outcome"] == "up-to-date"
    assert h.store.current_plan(h.iid, now=h.now) is None


def test_empty_identifier_classification_is_supported_without_decryption(imported):
    h = imported
    h.case.source = replace(
        h.case.source,
        sealed_keys=frozenset(),
        sealed_values={},
        entities=tuple(replace(entity, sealed_values={}) for entity in h.case.source.entities),
    )
    h.case.candidate = h.case.build_candidate(h.case.source)
    assert h.approve_scope().sealed_keys == []
    decision = h.stage()
    h.activate(decision)
    assert h.post("recompute", {}).json()["outcome"] == "issued"


def test_request_is_bounded_and_actor_strings_service_tokens_do_not_authorize(imported):
    h = imported
    root = f"/v1/installations/{h.iid}/configuration/import"
    response = h.client.post(
        root,
        content=b"x" * (4 * 1024 * 1024 + 65537),
        headers={**h.token(), "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert (
        h.client.post(
            root,
            json={"actor": "approver", "configuration_key": "self-asserted"},
            headers=h.token(),
        ).status_code
        == 422
    )
    assert (
        h.client.post(
            root, json={}, headers=h.token("approver", scp="", idtyp="app", roles=["Catalog.Read"])
        ).status_code
        == 403
    )
    assert h.client.post(root, json={}, headers=h.token("unapproved-operator")).status_code == 403


def test_history_byte_limit_rejects_before_advancing_head(imported, monkeypatch):
    h = imported
    h.approve_scope()
    first = h.stage()
    child = h.child("b")
    monkeypatch.setattr(
        "fdai_lifecycle_hub.configuration_import_store.MAX_HISTORY_BYTES",
        len(h.case.candidate.package.payload) + len(child.payload) - 1,
    )
    response = h.post("configuration/import", h.import_request(child, predecessor=first["digest"]))
    assert response.status_code == 409
    assert response.json()["error"] == "configuration_history_full"
    assert ConfigurationImportStore(h.engine).read(h.iid)["accepted_digest"] == first["digest"]


@pytest.mark.parametrize("gate", ["recall", "window"])
def test_default_persisted_consumer_retains_catalog_recall_and_maintenance_gates(
    imported, tmp_path, gate
):
    h = imported
    h.approve_scope()
    h.activate(h.stage())
    if gate == "recall":
        vendor = ReleaseStore(tmp_path / "release.db", h.key, clock=lambda: h.now)
        vendor.change(
            "recall",
            "1.6.0",
            Change(
                revision=vendor.snapshot()["revision"],
                confirmation="1.6.0",
                reason="Synthetic persisted consumer recall boundary",
            ),
        )
        raw = vendor.export()[0]
        h.catalog.fetch = lambda _: raw
        approve(h.catalog, raw, h.now)
        h.catalog.import_once(actor="approver", now=h.now)
        reason = "release_recalled"
    else:
        h.now += timedelta(hours=1)
        reported = h.store.load(h.iid).reported
        h.store.record_state(
            h.iid, replace(reported, digest="f" * 64, observed_at=h.now), now=h.now
        )
        reason = "maintenance_window_unavailable"
    response = h.post("recompute", {})
    assert response.status_code == 200, response.json()
    assert response.json()["outcome"] != "issued"
    assert reason in response.text
    assert h.store.current_plan(h.iid, now=h.now) is None
