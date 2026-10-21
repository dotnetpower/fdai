from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fdai_deployment_cli.lifecycle_configuration_package import (
    build_installation_configuration_package,
)
from fdai_deployment_cli.lifecycle_configuration_sealing import encryption_key_digest
from lifecycle.hub.tests.configuration_key_helpers import remote_auth, request_for, tokens
from lifecycle.hub.tests.test_configuration_revision import plan_case as plan_case
from lifecycle.hub.tests.test_hubs_postgres import databases as databases
from lifecycle.hub.tests.test_remote_catalog import approve, source_for
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from fdai_lifecycle_hub import audit, models
from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.configuration_key_store import ConfigurationKeyStore
from fdai_lifecycle_hub.configuration_keys import ConfigurationKeyRequest, KeyBindingError
from fdai_lifecycle_hub.domain import Issued
from fdai_lifecycle_hub.migrations import _versions, migrate, require_schema
from fdai_lifecycle_hub.remote import target_routes
from fdai_lifecycle_hub.remote_catalog import RemoteCatalog, initialize_trust, metadata
from fdai_lifecycle_hub.store import HubStore
from fdai_release_hub.store import ReleaseStore


def test_postgres_real_auth_durable_plan_rotation_history_restart_and_cas(
    databases, plan_case, installation_key, enroll, key, now, tmp_path, monkeypatch
):
    engine = databases["target"]
    source = source_for(key)

    def initialize(connection):
        models.Base.metadata.create_all(connection)
        metadata.create_all(connection)
        initialize_trust(connection, source)

    migrate(engine, "lifecycle_hub", initialize)
    require_schema(engine, "lifecycle_hub")
    store = HubStore(engine)
    case = plan_case
    iid = case.installation.installation_id
    enroll(
        store,
        replace(
            case.installation,
            settings=replace(case.installation.settings, plan_duration=timedelta(minutes=20)),
        ),
    )
    request, signed = request_for(
        installation_key, case.signing, case.recipient, now, installation_id=iid
    )
    registry = ConfigurationKeyStore(engine)
    vendor = ReleaseStore(tmp_path / "release.db", key, clock=lambda: now)
    raw, _ = vendor.export()
    catalog = RemoteCatalog(engine, source, fetch=lambda source: raw)
    approve(catalog, raw, now)
    catalog.import_once(actor="approver", now=now)
    auth = remote_auth()
    app = create_app(store, clock=lambda: now, remote_auth=auth)
    token = tokens(app, auth)
    monkeypatch.setattr("fdai_lifecycle_hub.remote.utc_now", lambda: now)
    app.routes[0:0] = target_routes(
        store, catalog, key, configuration_candidates={iid: (case.candidate, 1)}
    )
    key_root = f"/v1/installations/{iid}/configuration-keys"
    with TestClient(app, base_url=auth.origin) as client:
        assert (
            client.post(
                key_root + "/request", json=signed.model_dump(mode="json"), headers=token()
            ).status_code
            == 202
        )
        readback = client.get(key_root + "/requests/" + request.digest, headers=token("approver"))
        assert readback.status_code == 200
        assert readback.json()["request_digest"] == request.digest
        assert (
            client.post(
                key_root + "/approve",
                json={"request_digest": request.digest},
                headers=token("approver"),
            ).status_code
            == 202
        )
        outcome = client.post(
            f"/v1/installations/{iid}/recompute", json={}, headers=token("approver")
        )
        assert outcome.status_code == 200
        assert outcome.json()["outcome"] == "issued", outcome.json()
    restarted_engine = create_engine(engine.url, hide_parameters=True)
    try:
        restarted = HubStore(restarted_engine)
        assert ConfigurationKeyStore(restarted_engine).status(iid)["version"] == 1
        assert (
            restarted.current_plan(iid, now=now).configuration_digest
            == case.candidate.package.digest
        )
        rotations = []
        for _ in range(2):
            signer, recipient = Ed25519PrivateKey.generate(), X25519PrivateKey.generate()
            rotation, proof = request_for(
                installation_key,
                signer,
                recipient,
                now,
                installation_id=iid,
                version=2,
                predecessor=request.digest,
            )
            registry.request(iid, proof, actor="requester", now=now)
            rotations.append((rotation, signer, recipient))

        def accept(item):
            try:
                ConfigurationKeyStore(restarted_engine).approve(
                    iid, item[0].digest, actor="approver", now=now
                )
                return item
            except KeyBindingError:
                return None

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(accept, rotations))
        accepted = [item for item in results if item is not None]
        assert len(accepted) == 1
        rotation, signer, recipient = accepted[0]
        assert restarted.current_plan(iid, now=now) is None
        with pytest.raises(KeyBindingError, match="unavailable"):
            restarted.recompute_configuration(
                iid, case.candidate, binding_version=1, catalog=case.catalog, key=key, now=now
            )
        package = build_installation_configuration_package(
            replace(case.source, revision_id="b" * 40),
            entity_ids=frozenset(entity.entity_id for entity in case.source.entities),
            signing_key=signer,
            installation_key=recipient.public_key(),
        )
        rotated_candidate = replace(
            case.candidate,
            package=package,
            configuration_key=signer.public_key(),
            installation_key_digest=encryption_key_digest(recipient.public_key()),
        )
        result = restarted.recompute_configuration(
            iid, rotated_candidate, binding_version=2, catalog=case.catalog, key=key, now=now
        )
        assert isinstance(result, Issued)
        with Session(restarted_engine) as session:
            old = session.get(models.ConfigurationKeyRequest, request.digest)
            retained = ConfigurationKeyRequest.model_validate_json(old.payload)
            assert retained.configuration_signing_key != rotation.configuration_signing_key
            Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(retained.configuration_signing_key)
            ).verify(case.candidate.package.signature, case.candidate.package.payload)
            assert len(session.scalars(select(models.ConfigurationKeyBinding)).all()) == 2
            assert audit.chain_intact(session)
        registry.revoke(iid, rotation.digest, actor="approver", now=now)
        assert restarted.current_plan(iid, now=now) is None
        with pytest.raises(KeyBindingError, match="unavailable"):
            restarted.recompute_configuration(
                iid, rotated_candidate, binding_version=2, catalog=case.catalog, key=key, now=now
            )
    finally:
        restarted_engine.dispose()


def test_postgres_explicit_additive_migration_preserves_legacy_enrollment(
    databases, installation, enroll, planner, now
):
    engine = databases["target"]
    excluded = {
        "lifecycle_configuration_key_request",
        "lifecycle_configuration_key_binding",
        "lifecycle_configuration_plan_trust",
    }
    versions = _versions("lifecycle_hub")
    with engine.begin() as connection:
        models.Base.metadata.create_all(
            connection,
            tables=[
                table for table in models.Base.metadata.sorted_tables if table.name not in excluded
            ],
        )
        versions.create(connection)
        connection.execute(versions.insert().values(revision=1))
    store = HubStore(engine)
    enroll(store, installation)
    before = store.load(installation.installation_id)
    with pytest.raises(ValueError, match="migrate"):
        require_schema(engine, "lifecycle_hub")

    def no_reinitialize(connection):
        raise AssertionError("An existing schema must be upgraded, never initialized again.")

    migrate(engine, "lifecycle_hub", no_reinitialize)
    migrate(engine, "lifecycle_hub", no_reinitialize)
    require_schema(engine, "lifecycle_hub")
    assert store.load(installation.installation_id) == before
    assert ConfigurationKeyStore(engine).status(installation.installation_id)["version"] == 0
    assert isinstance(store.recompute(installation.installation_id, planner, now=now), Issued)
