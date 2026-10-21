from __future__ import annotations

from base64 import b64decode
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from lifecycle.hub.tests.configuration_import_helpers import make_harness
from lifecycle.hub.tests.configuration_key_helpers import tokens
from lifecycle.hub.tests.test_configuration_revision import plan_case as plan_case
from lifecycle.hub.tests.test_hubs_postgres import databases as databases
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from fdai_lifecycle_hub import audit, models
from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.configuration_import_models import (
    ConfigurationChangeApproval,
    ConfigurationHead,
    ConfigurationImport,
    ConfigurationPlanImport,
    ConfigurationScopeApproval,
    ConfigurationScopeRequest,
)
from fdai_lifecycle_hub.configuration_import_store import ConfigurationImportStore
from fdai_lifecycle_hub.configuration_keys import KeyBindingError
from fdai_lifecycle_hub.migrations import _versions, migrate, require_schema
from fdai_lifecycle_hub.remote import target_routes
from fdai_lifecycle_hub.remote_catalog import RemoteCatalog
from fdai_lifecycle_hub.store import HubStore


@pytest.fixture
def postgres_import(
    databases, plan_case, installation_key, key, now, sign, tmp_path, monkeypatch, request
):
    h = make_harness(
        databases["target"],
        plan_case,
        installation_key,
        key,
        now,
        sign,
        tmp_path,
        monkeypatch,
        plan_duration=timedelta(minutes=10) if hasattr(request, "param") else timedelta(minutes=20),
    )
    with h.client:
        changes = (
            {
                "binding_expires_at": now + request.param,
                "approval_expires_at": now + timedelta(minutes=1),
            }
            if hasattr(request, "param")
            else {}
        )
        h.register_keys(**changes)
        yield h


def test_postgres_actual_jwt_restart_original_bytes_and_default_consumer(postgres_import):
    h = postgres_import
    h.approve_scope()
    signed = h.import_request()
    first = h.stage(signed)
    h.activate(first)
    assert h.post("recompute", {}).json()["outcome"] == "issued"
    restarted_engine = create_engine(h.engine.url, hide_parameters=True)
    try:
        restarted = HubStore(restarted_engine)
        remote = RemoteCatalog(restarted_engine, h.catalog.source)
        app = create_app(restarted, clock=lambda: h.now, remote_auth=h.auth)
        app.routes[0:0] = target_routes(restarted, remote, h.key)
        token = tokens(app, h.auth)
        root = f"/v1/installations/{h.iid}"
        with TestClient(app, base_url=h.auth.origin) as client:
            response = client.post(
                root + "/configuration/import",
                json=signed.model_dump(mode="json"),
                headers=token(),
            )
            assert response.status_code == 202, response.json()
            assert response.json() == first
            readback = client.get(
                root + "/configuration/revisions/" + first["digest"], headers=token("approver")
            )
            assert b64decode(readback.json()["signed_container"]) == b64decode(
                signed.signed_container
            )
            outcome = client.post(root + "/recompute", json={}, headers=token("approver"))
            assert outcome.json()["outcome"] == "unchanged", outcome.json()
            assert "private-identifier" not in response.text + readback.text + outcome.text
        assert restarted.current_plan(h.iid, now=h.now).configuration_digest == first["digest"]
        with Session(restarted_engine) as session:
            plan = restarted.current_plan(h.iid, now=h.now)
            assert (
                session.get(ConfigurationPlanImport, plan.plan_id).receipt_digest
                == first["receipt_digest"]
            )
            assert session.scalar(select(func.count()).select_from(ConfigurationImport)) == 1
            assert audit.chain_intact(session)
    finally:
        restarted_engine.dispose()


def test_postgres_two_connections_reject_fork_and_roll_back_audit_failure(
    postgres_import, monkeypatch
):
    h = postgres_import
    h.approve_scope()
    first = h.stage()
    children = [h.child("b"), h.child("c")]
    requests = [h.import_request(child, predecessor=first["digest"]) for child in children]
    engines = [create_engine(h.engine.url, hide_parameters=True) for _ in range(2)]
    barrier = Barrier(2)
    try:
        with engines[0].connect() as left, engines[1].connect() as right:
            assert left.scalar(text("SELECT pg_backend_pid()")) != right.scalar(
                text("SELECT pg_backend_pid()")
            )

        def submit(index):
            barrier.wait(timeout=10)
            try:
                result = ConfigurationImportStore(engines[index]).import_revision(
                    h.iid, requests[index], actor="requester", now=h.now, catalog=h.case.catalog
                )
                return "accepted", result["digest"]
            except KeyBindingError as error:
                return "held", str(error)

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, range(2)))
        assert sorted(status for status, _ in outcomes) == ["accepted", "held"], outcomes
        assert next(reason for status, reason in outcomes if status == "held") == (
            "configuration_predecessor_conflict"
        )
        winner = next(
            child
            for child in children
            if any(status == "accepted" and digest == child.digest for status, digest in outcomes)
        )
        next_package = h.child("d", history=(h.case.candidate.package, winner))
        signed = h.import_request(next_package, predecessor=winner.digest)
        with Session(h.engine) as session:
            count = session.scalar(select(func.count()).select_from(models.AuditRecord))

        def fail_audit(*args, **kwargs):
            raise RuntimeError("synthetic PostgreSQL audit failure")

        with monkeypatch.context() as patch:
            patch.setattr("fdai_lifecycle_hub.configuration_import_store.audit.append", fail_audit)
            with pytest.raises(RuntimeError, match="synthetic PostgreSQL"):
                ConfigurationImportStore(engines[0]).import_revision(
                    h.iid, signed, actor="requester", now=h.now, catalog=h.case.catalog
                )
        with Session(h.engine) as session:
            assert session.get(ConfigurationHead, h.iid).accepted_digest == winner.digest
            assert session.get(ConfigurationImport, next_package.digest) is None
            assert session.scalar(select(func.count()).select_from(ConfigurationImport)) == 2
            assert session.scalar(select(func.count()).select_from(models.AuditRecord)) == count
            assert audit.chain_intact(session)
        assert h.stage(signed)["digest"] == next_package.digest
    finally:
        for engine in engines:
            engine.dispose()


@pytest.mark.parametrize("postgres_import", [timedelta(minutes=11)], indirect=True)
def test_postgres_rotation_preserves_old_receipt_but_revoked_history_holds(postgres_import):
    h = postgres_import
    h.approve_scope()
    first = h.stage()
    h.activate(first)
    h.now += timedelta(minutes=12)
    with Session(h.engine) as session:
        previous = session.get(models.ConfigurationKeyBinding, (h.iid, 1)).request_digest
    signer, recipient = Ed25519PrivateKey.generate(), X25519PrivateKey.generate()
    second_key = h.register_keys(
        signer=signer, recipient=recipient, version=2, predecessor=previous
    )
    assert h.post("configuration/import", h.import_request(version=1)).status_code == 409
    old_signer_child = h.child("c")
    assert (
        h.post(
            "configuration/import",
            h.import_request(old_signer_child, version=2, predecessor=first["digest"]),
        ).status_code
        == 409
    )
    package = h.child("b", signer=signer, recipient=recipient, bindings=(h.history_binding(),))
    second = h.stage(h.import_request(package, version=2, predecessor=first["digest"]))
    h.activate(second)
    reported = h.store.load(h.iid).reported
    h.store.record_state(h.iid, replace(reported, digest="d" * 64, observed_at=h.now), now=h.now)
    assert h.post("recompute", {}).json()["outcome"] == "issued"
    with Session(h.engine) as session:
        assert session.get(ConfigurationImport, first["digest"]).binding_digest == previous
        assert session.get(ConfigurationImport, package.digest).binding_digest == second_key.digest
        plan = h.store.current_plan(h.iid, now=h.now)
        assert session.get(models.ConfigurationPlanTrust, plan.plan_id).binding_version == 2
    with Session(h.engine) as session, session.begin():
        session.get(models.ConfigurationKeyBinding, (h.iid, 1)).revoked_at = h.now
    response = h.post("recompute", {})
    assert response.status_code == 409
    assert response.json()["error"] == "configuration_history_binding_unavailable"
    assert h.store.current_plan(h.iid, now=h.now) is None


def test_postgres_revision_two_upgrade_is_additive_and_preserves_legacy(postgres_import):
    h = postgres_import
    additions = (
        ConfigurationPlanImport,
        ConfigurationChangeApproval,
        ConfigurationHead,
        ConfigurationImport,
        ConfigurationScopeApproval,
        ConfigurationScopeRequest,
    )
    with Session(h.engine) as session:
        installation = session.get(models.Installation, h.iid)
        legacy_digest = installation.configuration_digest
        raw_legacy = installation.configuration.body
        original_identity = installation.installation_key
    with h.engine.begin() as connection:
        for model in additions:
            models.Base.metadata.tables[model.__tablename__].drop(connection)
        connection.execute(_versions("lifecycle_hub").update().values(revision=2))
    with pytest.raises(ValueError, match="migrate"):
        require_schema(h.engine, "lifecycle_hub")

    def never_initialize(connection):
        pytest.fail("An existing revision must not be initialized again")

    migrate(h.engine, "lifecycle_hub", never_initialize)
    require_schema(h.engine, "lifecycle_hub")
    with h.engine.connect() as connection:
        assert connection.scalar(select(_versions("lifecycle_hub").c.revision)) == 3
        assert all(inspect(connection).has_table(model.__tablename__) for model in additions)
    with Session(h.engine) as session:
        installation = session.get(models.Installation, h.iid)
        assert installation.configuration_digest == legacy_digest
        assert installation.configuration.body == raw_legacy
        assert installation.installation_key == original_identity
        assert session.get(models.ConfigurationKeyBinding, (h.iid, 1)) is not None
    h.approve_scope()
    assert h.stage()["digest"] == h.case.candidate.package.digest
