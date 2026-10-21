from __future__ import annotations

from base64 import b64encode
from dataclasses import replace
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fdai_deployment_cli.contracts import canonical_bytes
from lifecycle.hub.tests.configuration_key_helpers import remote_auth, request_for, tokens
from lifecycle.hub.tests.test_configuration_revision import plan_case as plan_case
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from fdai_lifecycle_hub import audit, models
from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.configuration_key_store import ConfigurationKeyStore
from fdai_lifecycle_hub.configuration_keys import KeyBindingError
from fdai_lifecycle_hub.domain import Issued
from fdai_lifecycle_hub.store import HubStore


@pytest.fixture
def keys(enrolled_store, installation, installation_key, now):
    signer, recipient = Ed25519PrivateKey.generate(), X25519PrivateKey.generate()
    request, signed = request_for(
        installation_key, signer, recipient, now, installation_id=installation.installation_id
    )
    return ConfigurationKeyStore(enrolled_store.engine), request, signed, signer, recipient


def test_actual_authenticated_independent_approval_and_restart(
    keys, enrolled_store, installation, now
):
    registry, request, signed, _, _ = keys
    auth = remote_auth()
    app = create_app(enrolled_store, clock=lambda: now, remote_auth=auth)
    token = tokens(app, auth)
    root = f"/v1/installations/{installation.installation_id}/configuration-keys"
    with TestClient(app, base_url=auth.origin) as client:
        body = signed.model_dump(mode="json")
        assert client.post(root + "/request", json=body).status_code == 401
        assert (
            client.post(
                root + "/request", json=body, headers={"X-MS-CLIENT-PRINCIPAL": "requester"}
            ).status_code
            == 401
        )
        assert (
            client.post(root + "/request", json=body, headers=token(scp="other")).status_code == 403
        )
        assert client.post(root + "/request", json=body, headers=token()).status_code == 202
        approval = {"request_digest": request.digest}
        assert (
            client.post(
                root + "/approve", json={**approval, "approver": "approver"}, headers=token()
            ).status_code
            == 422
        )
        assert client.post(root + "/approve", json=approval, headers=token()).status_code == 409
        assert registry.status(installation.installation_id)["version"] == 0
        assert (
            client.post(
                root + "/approve",
                json=approval,
                headers=token("approver", scp=None, roles=["Hub.Access"]),
            ).status_code
            == 403
        )
        assert (
            client.post(root + "/approve", json=approval, headers=token("approver")).status_code
            == 202
        )
        assert (
            client.post(root + "/approve", json=approval, headers=token("approver")).status_code
            == 409
        )
    restarted = ConfigurationKeyStore(HubStore(enrolled_store.engine).engine)
    assert restarted.status(installation.installation_id)["request_digest"] == request.digest
    with Session(enrolled_store.engine) as session:
        assert audit.chain_intact(session)
        denied = session.scalars(
            select(models.AuditRecord).where(
                models.AuditRecord.action == "configuration.keys.denied"
            )
        ).all()
        assert len(denied) >= 2
        saved = session.get(models.ConfigurationKeyRequest, request.digest)
        assert saved.payload == request.payload
        assert saved.identity_proof == signed.identity_proof


def test_unauthenticated_loopback_cannot_register_or_approve(
    keys, enrolled_store, installation, now
):
    _, request, signed, _, _ = keys
    with TestClient(create_app(enrolled_store, clock=lambda: now)) as client:
        root = f"/v1/installations/{installation.installation_id}/configuration-keys"
        assert (
            client.post(root + "/request", json=signed.model_dump(mode="json")).status_code == 403
        )
        assert (
            client.post(
                root + "/approve", json={"request_digest": request.digest, "approver": "approver"}
            ).status_code
            == 403
        )


@pytest.mark.parametrize(
    "fault", ["unsigned", "signer", "identity", "installation", "requester", "stale"]
)
def test_bad_request_never_establishes_trust(
    fault, keys, enrolled_store, installation_key, installation, now
):
    registry, request, signed, signer, recipient = keys
    if fault in {"unsigned", "signer", "identity"}:
        field = "signer_proof" if fault == "signer" else "identity_proof"
        signed = signed.model_copy(update={field: b"" if fault == "unsigned" else b"x" * 64})
    elif fault == "installation":
        request, signed = request_for(
            installation_key, signer, recipient, now, installation_id="other"
        )
    elif fault == "requester":
        request, signed = request_for(
            installation_key,
            signer,
            recipient,
            now,
            installation_id=installation.installation_id,
            requester="other",
        )
    else:
        request, signed = request_for(
            installation_key,
            signer,
            recipient,
            now - timedelta(minutes=6),
            installation_id=installation.installation_id,
        )
    with pytest.raises(KeyBindingError):
        registry.request(installation.installation_id, signed, actor="requester", now=now)
    assert registry.status(installation.installation_id)["version"] == 0
    with Session(enrolled_store.engine) as session:
        assert audit.chain_intact(session)
        assert (
            session.scalar(
                select(models.AuditRecord.action).order_by(models.AuditRecord.sequence.desc())
            )
            == "configuration.keys.denied"
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"signing_algorithm": "X25519"},
        {"encryption_algorithm": "Ed25519"},
        {"installation_encryption_key": "0" * 64},
        {"configuration_signing_key": "not-public-key"},
        {"version": True},
        {"private_key": "not-accepted"},
    ],
)
def test_roles_public_shape_and_low_order_key_are_checked(keys, installation_key, now, changes):
    _, _, _, signer, recipient = keys
    with pytest.raises(ValidationError):
        request_for(installation_key, signer, recipient, now, **changes)


def test_identity_cannot_be_reused_for_configuration(keys, installation_key, installation, now):
    registry, _, _, _, recipient = keys
    _, signed = request_for(
        installation_key,
        installation_key,
        recipient,
        now,
        installation_id=installation.installation_id,
    )
    with pytest.raises(KeyBindingError, match="identity_mismatch"):
        registry.request(installation.installation_id, signed, actor="requester", now=now)


def test_expiry_predecessor_replay_and_explicit_rotation(keys, installation, installation_key, now):
    registry, request, signed, _, _ = keys
    iid = installation.installation_id
    registry.request(iid, signed, actor="requester", now=now)
    with pytest.raises(KeyBindingError, match="replayed"):
        registry.request(iid, signed, actor="requester", now=now)
    with pytest.raises(KeyBindingError, match="expired"):
        registry.approve(iid, request.digest, actor="approver", now=now + timedelta(minutes=10))
    registry.approve(iid, request.digest, actor="approver", now=now + timedelta(minutes=9))
    next_signer, next_recipient = Ed25519PrivateKey.generate(), X25519PrivateKey.generate()
    _, wrong = request_for(
        installation_key,
        next_signer,
        next_recipient,
        now,
        installation_id=iid,
        version=2,
        predecessor="sha256:" + "0" * 64,
    )
    with pytest.raises(KeyBindingError, match="conflict"):
        registry.request(iid, wrong, actor="requester", now=now)
    rotation, signed_rotation = request_for(
        installation_key,
        next_signer,
        next_recipient,
        now,
        installation_id=iid,
        version=2,
        predecessor=request.digest,
    )
    registry.request(iid, signed_rotation, actor="requester", now=now)
    registry.approve(iid, rotation.digest, actor="approver", now=now)
    with pytest.raises(KeyBindingError, match="conflict"):
        registry.approve(iid, request.digest, actor="approver", now=now)
    registry.revoke(iid, rotation.digest, actor="approver", now=now)
    assert registry.status(iid)["version"] == 2
    assert registry.status(iid)["revoked"] is True


def test_actual_planning_resolves_persisted_binding_and_holds_mismatches(
    store, enroll, plan_case, installation_key, key, now
):
    case = plan_case
    iid = case.installation.installation_id
    enroll(store, case.installation)
    registry = ConfigurationKeyStore(store.engine)
    request, signed = request_for(
        installation_key, case.signing, case.recipient, now, installation_id=iid
    )

    def compute(candidate=case.candidate, version=1, at=now):
        return HubStore(store.engine).recompute_configuration(
            iid, candidate, binding_version=version, catalog=case.catalog, key=key, now=at
        )

    with pytest.raises(KeyBindingError, match="unavailable"):
        compute()
    registry.request(iid, signed, actor="requester", now=now)
    with pytest.raises(KeyBindingError, match="unavailable"):
        compute()
    registry.approve(iid, request.digest, actor="approver", now=now)
    outcome = compute()
    assert isinstance(outcome, Issued)
    assert outcome.plan.configuration_revision_digest == case.candidate.package.digest
    for bad in (
        replace(case.candidate, configuration_key=Ed25519PrivateKey.generate().public_key()),
        replace(case.candidate, installation_id="other"),
        replace(case.candidate, installation_key_digest="sha256:" + "0" * 64),
    ):
        with pytest.raises(KeyBindingError, match="mismatch"):
            compute(bad)
    with pytest.raises(KeyBindingError, match="unavailable"):
        compute(version=2)
    with pytest.raises(KeyBindingError, match="expired"):
        compute(at=now + timedelta(days=1))
    registry.revoke(iid, request.digest, actor="approver", now=now)
    with pytest.raises(KeyBindingError, match="unavailable"):
        compute()
    with Session(store.engine) as session:
        assert audit.chain_intact(session)
        assert (
            session.get(models.ConfigurationKeyRequest, request.digest).payload == request.payload
        )


def test_noncanonical_body_cannot_reuse_proof(keys, installation, now):
    registry, _, signed, _, _ = keys
    raw = signed.signed_payload + b" "
    wire = signed.model_dump(mode="json")
    wire["signed_payload"] = b64encode(raw).decode()
    with pytest.raises(KeyBindingError):
        registry.request(
            installation.installation_id,
            type(signed).model_validate(wire),
            actor="requester",
            now=now,
        )


def test_missing_configuration_binding_does_not_withdraw_legacy_plan(
    enrolled_store, installation, planner, plan_case, key, now
):
    iid = installation.installation_id
    legacy = enrolled_store.recompute(iid, planner, now=now)
    assert isinstance(legacy, Issued)
    with pytest.raises(KeyBindingError, match="unavailable"):
        enrolled_store.recompute_configuration(
            iid, plan_case.candidate, binding_version=1, catalog=plan_case.catalog, key=key, now=now
        )
    retained = enrolled_store.current_plan(iid, now=now)
    assert retained is not None
    assert retained.plan_id == legacy.plan.plan_id
    assert retained.signature == legacy.plan.signature


def test_identity_point_signature_is_not_proof_of_configuration_key_possession(
    keys, installation_key, installation, now
):
    registry, request, signed, _, _ = keys
    identity_point = b"\x01" + bytes(31)
    forged_signature = identity_point + bytes(32)
    document = request.model_dump(mode="json")
    document["configuration_signing_key"] = identity_point.hex()
    payload = canonical_bytes(document)
    # Reproduce the provider behavior; this is public synthetic material, not a private key.
    Ed25519PublicKey.from_public_bytes(identity_point).verify(forged_signature, payload)
    wire = signed.model_dump(mode="json")
    wire.update(
        signed_payload=b64encode(payload).decode(),
        identity_proof=b64encode(installation_key.sign(payload)).decode(),
        signer_proof=b64encode(forged_signature).decode(),
    )
    with pytest.raises(KeyBindingError, match="configuration_request_invalid"):
        registry.request(
            installation.installation_id,
            type(signed).model_validate(wire),
            actor="requester",
            now=now,
        )
    assert registry.status(installation.installation_id)["version"] == 0


@pytest.mark.parametrize(
    "encoded",
    [
        "00" * 32,
        "01" + "00" * 31,
        "ec" + "ff" * 30 + "7f",
        "ed" + "ff" * 30 + "7f",
        "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
        "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
    ],
)
def test_noncanonical_and_small_order_signing_points_hold(keys, installation_key, now, encoded):
    _, _, _, signer, recipient = keys
    with pytest.raises(ValidationError):
        request_for(installation_key, signer, recipient, now, configuration_signing_key=encoded)
