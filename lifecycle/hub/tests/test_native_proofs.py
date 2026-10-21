from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_native import sign_native_scope
from lifecycle.hub.tests import test_native_ownership as native_cases
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from fdai_lifecycle_hub import audit, cli, models
from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.native_ownership import NativeOwnershipError
from fdai_lifecycle_hub.native_proofs import NativeProofStore
from fdai_lifecycle_hub.store import HubStore

native_store = native_cases.native_store
acceptance = native_cases.acceptance


def test_submission_is_durable_idempotent_and_does_not_grant_ownership(
    native_store, installation_key, now
):
    store = native_store
    command = acceptance(store, installation_key)
    before = store.load("installation-alpha")
    service = NativeProofStore(store)
    assert service.submit("installation-alpha", command.proof, principal="agent", now=now)
    restarted = NativeProofStore(HubStore(store.engine))
    assert not restarted.submit("installation-alpha", command.proof, principal="agent", now=now)
    assert restarted.load("installation-alpha", command.proof.claim.digest) == command.proof
    assert store.load("installation-alpha") == before
    with Session(store.engine) as session:
        records = session.scalars(
            select(models.AuditRecord).where(
                models.AuditRecord.action == "entity.native_proof_submitted"
            )
        ).all()
        assert len(records) == 1
        assert records[0].payload["principal"] == "agent"
        assert audit.chain_intact(session)


@pytest.mark.parametrize("change", ["installation", "signature", "application", "conflict"])
def test_submission_denials_preserve_state_and_audit(native_store, installation_key, now, change):
    store = native_store
    command = acceptance(store, installation_key)
    service = NativeProofStore(store)
    if change == "conflict":
        service.submit("installation-alpha", command.proof, principal="agent", now=now)
    claim = command.proof.claim
    if change == "installation":
        claim = claim.model_copy(update={"installation_id": "another-installation"})
    if change == "application":
        claim = claim.model_copy(update={"product": "another-application"})
    if change == "conflict":
        claim = claim.model_copy(update={"scope_digest": "sha256:" + "d" * 64})
    key = Ed25519PrivateKey.generate() if change == "signature" else installation_key
    proof = sign_native_scope(claim, key)
    with Session(store.engine) as session:
        before = session.scalars(select(models.AuditRecord.record_hash)).all()
    with pytest.raises(NativeOwnershipError, match="native_proof_"):
        service.submit("installation-alpha", proof, principal="agent", now=now)
    with Session(store.engine) as session:
        assert session.scalars(select(models.AuditRecord.record_hash)).all() == before


def test_submitted_proof_cli_acceptance_still_requires_all_operator_inputs(
    native_store, installation_key, now, monkeypatch, capsys
):
    from fdai_lifecycle_hub import domain

    command = acceptance(native_store, installation_key)
    NativeProofStore(native_store).submit(
        "installation-alpha", command.proof, principal="agent", now=now
    )
    monkeypatch.setattr(cli, "_store", lambda: native_store)
    monkeypatch.setattr(domain, "utc_now", lambda: now)
    arguments = [
        "accept-native-ownership",
        "installation-alpha",
        "--submitted-proof",
        command.proof.claim.digest,
        "--request-id",
        str(command.request_id),
        "--settings-digest",
        command.expected_settings_digest,
        "--reason",
        command.reason,
        "--confirmation",
        command.required_confirmation,
        "--operator",
        "owner",
    ]
    assert cli.main(arguments) == 0
    assert json.loads(capsys.readouterr().out) == {"accepted": True, "changed": True}
    assert cli.main(arguments) == 0
    assert json.loads(capsys.readouterr().out) == {"accepted": True, "changed": False}
    assert cli.main(arguments + ["--confirmation", "wrong-confirmation"]) == 1
    assert command.proof.signature not in capsys.readouterr().err
    assert cli.main(["accept-native-ownership", "installation-alpha", "--operator", "owner"]) == 1
    assert "native_ownership_request_required" in capsys.readouterr().err


def test_proof_lookup_is_installation_bound_and_has_no_http_read_route(
    native_store, installation_key, now
):
    proof = acceptance(native_store, installation_key).proof
    service = NativeProofStore(native_store)
    service.submit("installation-alpha", proof, principal="agent", now=now)
    for digest in ("invalid", "sha256:" + "0" * 64):
        with pytest.raises(NativeOwnershipError):
            service.load("installation-alpha", digest)
    with TestClient(create_app(native_store)) as client:
        path = "/v1/installations/installation-alpha/native-proofs"
        assert client.get(path).status_code == 405
        assert client.post(path, json=json.loads(proof.model_dump_json())).status_code == 403


def test_trusted_binding_cli_keeps_request_confirmation_and_sanitizes_input(
    enrolled_store, installation, now, monkeypatch, capsys, tmp_path
):
    from lifecycle.hub.tests.test_application_binding import command

    from fdai_lifecycle_hub import domain

    request = command(enrolled_store, installation.installation_id, "example-app")
    path = tmp_path / "binding.json"
    path.write_text(request.model_dump_json())
    monkeypatch.setattr(cli, "_store", lambda: enrolled_store)
    monkeypatch.setattr(domain, "utc_now", lambda: now)
    args = ["bind-application", installation.installation_id, str(path), "--operator", "owner"]
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out) == {"bound": True, "changed": True}
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out) == {"bound": True, "changed": False}
    path.write_text('{"private":"do-not-print-this"}')
    assert cli.main(args) == 1
    assert "do-not-print-this" not in capsys.readouterr().err


def test_remote_cli_uses_existing_mi_engine_without_local_fallback(hub_store, monkeypatch):
    from fdai_lifecycle_hub import remote
    from fdai_lifecycle_hub.migrations import migrate

    migrate(hub_store.engine, "lifecycle_hub", models.Base.metadata.create_all)
    monkeypatch.setenv(
        "FDAI_HUB_REMOTE_CONFIG", '{"kind":"target","origin":"https://hub.example.com"}'
    )
    monkeypatch.setenv(cli.DATABASE_URL_ENV, "invalid-local-fallback")
    calls = []

    def engine(kind):
        calls.append(kind)
        return hub_store.engine

    monkeypatch.setattr(remote, "remote_engine", engine)
    assert cli._store().engine is hub_store.engine
    assert calls == ["target"]
    monkeypatch.setenv(
        "FDAI_HUB_REMOTE_CONFIG", '{"kind":"release","origin":"https://hub.example.com"}'
    )
    with pytest.raises(ValueError, match="target Hub"):
        cli._store()
    monkeypatch.setenv("FDAI_HUB_REMOTE_CONFIG", "private-invalid-input")
    with pytest.raises(ValueError, match="remote configuration is invalid") as failure:
        cli._store()
    assert "private-invalid-input" not in str(failure.value)
    monkeypatch.setenv("FDAI_HUB_REMOTE_CONFIG", "")
    with pytest.raises(ValueError, match="remote configuration is invalid"):
        cli._store()


def test_submitted_proof_cannot_bypass_current_signature_or_settings_checks(
    native_store, installation_key, now, monkeypatch, capsys
):
    from fdai_lifecycle_hub import domain
    from fdai_lifecycle_hub.native_ownership import NativeOwnershipStore

    command = acceptance(native_store, installation_key)
    inbox = NativeProofStore(native_store)
    inbox.submit("installation-alpha", command.proof, principal="agent", now=now)
    stored = inbox.load("installation-alpha", command.proof.claim.digest)
    service = NativeOwnershipStore(native_store)
    stale = command.model_copy(update={"proof": stored, "expected_settings_digest": "0" * 64})
    with pytest.raises(NativeOwnershipError, match="revision_conflict"):
        service.accept("installation-alpha", stale, operator="owner", now=now)
    with Session(native_store.engine) as session:
        row = session.get(models.Installation, "installation-alpha")
        assert row is not None
        row.installation_key = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        session.commit()
    monkeypatch.setattr(cli, "_store", lambda: native_store)
    monkeypatch.setattr(domain, "utc_now", lambda: now)
    arguments = [
        "accept-native-ownership",
        "installation-alpha",
        "--submitted-proof",
        command.proof.claim.digest,
        "--request-id",
        str(command.request_id),
        "--settings-digest",
        command.expected_settings_digest,
        "--reason",
        command.reason,
        "--confirmation",
        command.required_confirmation,
        "--operator",
        "owner",
    ]
    assert cli.main(arguments) == 1
    assert "native_ownership_signature_invalid" in capsys.readouterr().err


def test_pending_preparation_blocks_remote_cli(hub_store, monkeypatch):
    from fdai_lifecycle_hub import remote
    from fdai_lifecycle_hub.migrations import _versions, migrate

    migrate(hub_store.engine, "lifecycle_hub", models.Base.metadata.create_all)
    with hub_store.engine.begin() as connection:
        connection.execute(_versions("lifecycle_hub").update().values(revision=5))
    migrate(hub_store.engine, "lifecycle_hub", models.Base.metadata.create_all, prepare=True)
    monkeypatch.setenv(
        "FDAI_HUB_REMOTE_CONFIG", '{"kind":"target","origin":"https://hub.example.com"}'
    )
    monkeypatch.setattr(remote, "remote_engine", lambda _: hub_store.engine)
    with pytest.raises(ValueError):
        cli._store()


def test_preparation_blocks_actual_submission_without_retaining_a_claim(
    native_store, installation_key, now
):
    from fdai_lifecycle_hub.errors import SchemaMigrationPendingError
    from fdai_lifecycle_hub.migrations import _versions, migrate

    proof = acceptance(native_store, installation_key).proof
    with native_store.engine.begin() as connection:
        connection.execute(_versions("lifecycle_hub").update().values(revision=5))
    migrate(native_store.engine, "lifecycle_hub", models.Base.metadata.create_all, prepare=True)
    with pytest.raises(SchemaMigrationPendingError):
        NativeProofStore(native_store).submit(
            "installation-alpha", proof, principal="agent", now=now
        )
    with Session(native_store.engine) as session:
        assert not session.scalars(
            select(models.AuditRecord).where(
                models.AuditRecord.action == "entity.native_proof_submitted"
            )
        ).all()


@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_submissions_serialize_one_claim_per_entity(
    native_store, installation_key, now, conflicting
):
    if native_store.engine.dialect.name != "postgresql":
        pytest.skip("Concurrent row-lock behavior is exercised on actual PostgreSQL.")
    first = acceptance(native_store, installation_key).proof
    second = (
        sign_native_scope(
            first.claim.model_copy(update={"scope_digest": "sha256:" + "e" * 64}),
            installation_key,
        )
        if conflicting
        else first
    )
    barrier = Barrier(2, timeout=5)

    def submit(proof):
        barrier.wait()
        try:
            return NativeProofStore(HubStore(native_store.engine)).submit(
                "installation-alpha", proof, principal="agent", now=now
            )
        except NativeOwnershipError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit, proof) for proof in (first, second)]
        results = [future.result(timeout=10) for future in futures]
    assert results.count(True) == 1
    assert results.count("native_proof_claim_conflict" if conflicting else False) == 1
    with Session(native_store.engine) as session:
        assert (
            len(
                session.scalars(
                    select(models.AuditRecord).where(
                        models.AuditRecord.action == "entity.native_proof_submitted"
                    )
                ).all()
            )
            == 1
        )
        assert audit.chain_intact(session)


def test_cli_sanitizes_remote_storage_failures(monkeypatch, capsys):
    def unavailable():
        raise OperationalError(
            "private-sql-marker",
            {"private": "private-parameter-marker"},
            OSError("private-host-marker"),
        )

    monkeypatch.setattr(cli, "_store", unavailable)
    assert cli.main(["show", "installation-alpha"]) == 1
    output = capsys.readouterr()
    assert "verify storage, identity and inputs" in output.err
    assert "private-" not in output.out + output.err
