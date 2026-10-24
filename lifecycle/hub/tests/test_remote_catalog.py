from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import azure.identity
import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.contracts import canonical_bytes
from sqlalchemy import create_engine, select

from fdai_lifecycle_hub.agent_artifacts import artifact_for_plan
from fdai_lifecycle_hub.migrations import migrate, require_schema
from fdai_lifecycle_hub.operations import (
    CatalogImportRequest,
    RecomputeRequest,
    approve_and_import_catalog,
    recompute_installation,
)
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.remote_catalog import (
    CatalogSource,
    PinApproval,
    RemoteCatalog,
    bind_catalog,
    fetch_export,
    initialize_trust,
    trust_events,
)
from fdai_release_hub.store import Change, ReleaseStore


def test_catalog_can_be_bound_after_standalone_migration(tmp_path, key):
    from fdai_lifecycle_hub.remote_catalog import metadata

    engine = create_engine(f"sqlite:///{tmp_path / 'standalone.db'}")
    migrate(engine, "lifecycle_hub", metadata.create_all)
    source = source_for(key)
    with pytest.raises(ValueError, match="not bound"):
        RemoteCatalog(engine, source).status()
    bind_catalog(engine, source, actor="operator", reason="Independent source approval")
    bind_catalog(engine, source, actor="operator", reason="Idempotent repeat")
    assert RemoteCatalog(engine, source).status()["approved_sha256"] is None
    with engine.connect() as connection:
        assert len(connection.execute(select(trust_events)).all()) == 1
    other = source.model_copy(
        update={
            "release_public_key": Ed25519PrivateKey.generate()
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        }
    )
    with pytest.raises(ValueError, match="rotation"):
        bind_catalog(engine, other, actor="operator", reason="Must not silently rebind")


def source_for(key):
    return CatalogSource(
        url="https://release.example.com/v1/catalog/export",
        token_scope="api://vendor/.default",
        managed_identity_client_id="customer-client",
        release_public_key=key.public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode(),
    )


def approve(target, raw, now):
    digest = hashlib.sha256(raw).hexdigest()
    revision = json.loads(raw)["revision"]
    target.approve(
        PinApproval(
            revision=revision,
            sha256=digest,
            reason="Independent customer review",
            confirmation=f"approve {revision} {digest}",
        ),
        actor="customer-operator",
        now=now,
    )


def vendor_for(tmp_path, key, catalog, now):
    vendor = ReleaseStore(tmp_path / "vendor.db", key, clock=lambda: now)
    for version in ("1.5.0", "1.6.0"):
        for action in ("register", "publish"):
            vendor.change(
                action,
                version,
                Change(
                    revision=vendor.snapshot()["revision"],
                    confirmation=version,
                    reason="Synthetic development validation",
                    manifest=canonical_bytes(catalog.releases[version].to_mapping()).decode()
                    if action == "register"
                    else None,
                ),
            )
    return vendor


def test_read_only_release_inventory_uses_accepted_catalog(
    tmp_path, key, catalog, now, store, monkeypatch
):
    from starlette.testclient import TestClient

    from fdai_lifecycle_hub.api import create_app
    from fdai_lifecycle_hub.remote import target_routes

    vendor = vendor_for(tmp_path, key, catalog, now)
    raw = vendor.export()[0]
    source = source_for(key)
    engine = create_engine(f"sqlite:///{tmp_path / 'inventory.db'}")
    migrate(engine, "lifecycle_hub", lambda c: initialize_trust(c, source))
    target = RemoteCatalog(engine, source, fetch=lambda _: raw)
    approve(target, raw, now)
    target.import_once(actor="operator", now=now)
    target.fetch = lambda _: pytest.fail("GET must not fetch or import a catalog")
    before = target.status()
    monkeypatch.setattr("fdai_lifecycle_hub.remote.utc_now", lambda: now)
    app = create_app(store)
    app.routes[0:0] = target_routes(store, target, key)
    with TestClient(app) as client:
        response = client.get("/v1/catalog/releases")
        assert response.status_code == 200
        releases = response.json()["releases"]
        assert [item["release_id"] for item in releases] == ["1.5.0", "1.6.0"]
        first = releases[0]
        assert first["digest"] == catalog.releases["1.5.0"].digest
        assert first["channels"] == ["DEV"]
        assert first["schema_target"] == 15
        assert first["schema_range"] == {"minimum": 12, "maximum": 16}
        assert len(first["images"]) == 9
        assert all(
            set(image) == {"section", "component", "image_digest"} for image in first["images"]
        )
        assert first["recall_notices"] == []
        assert client.post("/v1/catalog/releases", json={}).status_code == 405
        monkeypatch.setattr("fdai_lifecycle_hub.remote.utc_now", lambda: now + timedelta(days=2))
        unavailable = client.get("/v1/catalog/releases")
        assert unavailable.status_code == 503
        assert unavailable.json() == {"error": "catalog_unavailable_review_trust_and_expiry"}
    assert target.status() == before


def test_release_inventory_refuses_unimported_catalog(tmp_path, key, store, now):
    from starlette.testclient import TestClient

    from fdai_lifecycle_hub.api import create_app
    from fdai_lifecycle_hub.remote import target_routes

    source = source_for(key)
    engine = create_engine(f"sqlite:///{tmp_path / 'unimported.db'}")
    migrate(engine, "lifecycle_hub", lambda c: initialize_trust(c, source))
    target = RemoteCatalog(engine, source, fetch=lambda _: pytest.fail("GET must not fetch"))
    app = create_app(store)
    app.routes[0:0] = target_routes(store, target, key)
    with TestClient(app) as client:
        assert client.get("/v1/catalog/releases").status_code == 503
    assert target.status()["minimum_revision"] == 0


def test_separate_pin_channel_persistence_planner_and_recall(
    tmp_path,
    key,
    catalog,
    installation,
    store,
    enroll,
    now,
):
    vendor = vendor_for(tmp_path, key, catalog, now)
    raw = vendor.export()[0]
    engine = create_engine(f"sqlite:///{tmp_path / 'trust.db'}")
    source = source_for(key)
    migrate(engine, "lifecycle_hub", lambda c: initialize_trust(c, source))
    target = RemoteCatalog(engine, source, fetch=lambda _: raw)
    with pytest.raises(ValueError, match="Approve"):
        target.import_once(actor="customer-operator", now=now)
    digest = hashlib.sha256(raw).hexdigest()
    revision = json.loads(raw)["revision"]
    import_request = CatalogImportRequest(
        schema_version="fdai.catalog-import-request.v1",
        request_id="00000000-0000-0000-0000-000000000001",
        revision=revision,
        sha256=digest,
        reason="Independent customer review",
        confirmation=f"approve {revision} {digest}",
    )
    imported_receipt = approve_and_import_catalog(
        target,
        import_request,
        actor="customer-operator",
        now=now,
    )
    assert imported_receipt["mutation_performed"] is True
    # The operation above imported the exact pin; a repeat is an effect-free readback.
    assert (
        approve_and_import_catalog(
            target,
            import_request,
            actor="customer-operator",
            now=now,
        )["mutation_performed"]
        is False
    )
    restarted = RemoteCatalog(create_engine(engine.url), source, fetch=lambda _: raw)
    assert restarted.status()["minimum_revision"] == 4
    target_installation = replace(
        installation,
        settings=replace(installation.settings, channel="DEV", plan_duration=timedelta(minutes=25)),
        reported=replace(installation.reported, observed_at=now),
    )
    enroll(store, target_installation)
    outcome, recompute_receipt = recompute_installation(
        store,
        restarted,
        key,
        RecomputeRequest(
            schema_version="fdai.lifecycle-recompute-request.v1",
            request_id="00000000-0000-0000-0000-000000000002",
            installation_id=target_installation.installation_id,
            catalog_revision=revision,
            catalog_sha256=digest,
        ),
        now=now,
    )
    assert outcome.plan.target_release_id == "1.6.0"
    assert recompute_receipt["mutation_performed"] is True
    artifact = artifact_for_plan(
        store,
        restarted,
        target_installation.installation_id,
        "release",
        catalog.releases["1.6.0"].digest,
        now=now,
    )
    assert artifact.payload == canonical_bytes(catalog.releases["1.6.0"].to_mapping())
    assert len(artifact.signature) == 64
    with pytest.raises(ValueError, match="differs from the current Plan"):
        artifact_for_plan(
            store,
            restarted,
            target_installation.installation_id,
            "release",
            "f" * 64,
            now=now,
        )
    # Removing the synthetic registry facts blocks selection; publication is not artifact proof.
    absent = replace(
        target_installation,
        reported=replace(
            target_installation.reported,
            entities={
                entity_id: replace(state, artifact_digests=frozenset())
                for entity_id, state in target_installation.reported.entities.items()
            },
        ),
    )
    missing = plan_next(absent, now, catalog=restarted.catalog(now), key=key)
    assert missing.kind == "no-eligible-release"
    vendor.change(
        "recall",
        "1.6.0",
        Change(
            revision=4,
            confirmation="1.6.0",
            reason="Withdraw synthetic candidate",
        ),
    )
    raw = vendor.export()[0]
    with pytest.raises(ValueError, match="digest"):
        target.import_once(actor="customer-operator", now=now)
    approve(target, raw, now)
    target.import_once(actor="customer-operator", now=now)
    decision = plan_next(target_installation, now, catalog=target.catalog(now), key=key)
    assert decision.plan.target_release_id == "1.5.0"
    with engine.connect() as connection:
        assert len(connection.execute(select(trust_events)).all()) == 4
    with pytest.raises(ValueError, match="expired"):
        target.catalog(now + timedelta(days=2))


@pytest.mark.parametrize("mode", ["tamper", "expiry", "lower", "same", "wrong-key"])
def test_import_rejections_never_change_persisted_floor(tmp_path, key, catalog, now, mode):
    vendor = vendor_for(tmp_path, key, catalog, now)
    raw = vendor.export()[0]
    source = source_for(key)
    engine = create_engine(f"sqlite:///{tmp_path / 'trust.db'}")
    migrate(engine, "lifecycle_hub", lambda c: initialize_trust(c, source))
    target = RemoteCatalog(engine, source, fetch=lambda _: raw)
    approve(target, raw, now)
    target.import_once(actor="operator", now=now)
    before = target.status()
    if mode == "tamper":
        raw += b" "
    elif mode == "expiry":
        with pytest.raises(ValueError, match="expired"):
            target.import_once(actor="operator", now=now + timedelta(days=2))
        assert target.status() == before
        return
    elif mode in {"lower", "same"}:
        payload = json.loads(raw)
        payload["revision"] = 3 if mode == "lower" else 4
        payload["channels"]["RELEASE"] = ["1.6.0"]
        raw = canonical_bytes(payload)
        with pytest.raises(ValueError, match="backwards|without a new revision"):
            approve(target, raw, now)
    else:
        from fdai_lifecycle_hub.signing import HubSigningKey

        target.source = source_for(HubSigningKey(Ed25519PrivateKey.generate(), 1))
    with pytest.raises(ValueError, match="digest|persisted trust"):
        target.import_once(actor="operator", now=now)
    target.source = source
    assert target.status() == before


def test_explicit_migrations_preserve_legacy_release_and_are_required(tmp_path, key):
    import sqlite3

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE metadata (created_at TEXT NOT NULL);
            INSERT INTO metadata VALUES ('2026-10-15T00:00:00+00:00');
        """)
    engine = create_engine(f"sqlite:///{path}")
    with pytest.raises(ValueError, match="migrated"):
        require_schema(engine, "release_hub")
    store = ReleaseStore(engine, key)
    store.migrate()
    assert store.snapshot()["updated_at"] == "2026-10-15T00:00:00+00:00"
    require_schema(engine, "release_hub")


@pytest.mark.parametrize(
    "url",
    [
        "http://release.example.com/v1/catalog/export",
        "https://release.example.com/other",
        "https://user@release.example.com/v1/catalog/export",
    ],
)
def test_catalog_endpoint_is_explicit_https(tmp_path, key, url):
    with pytest.raises(ValueError):
        source_for(key).model_copy(update={"url": url}).validate_source()


@pytest.mark.parametrize("mode", ["redirect", "compressed", "oversize", "valid", "identity"])
def test_transport_bounds_without_live_identity_or_network(monkeypatch, key, mode):
    from azure.core.exceptions import AzureError

    class Identity:
        def __init__(self, **kwargs):
            assert kwargs["client_id"] == "customer-client" and kwargs["retry_total"] == 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get_token(self, scope):
            assert scope == "api://vendor/.default"
            if mode == "identity":
                raise AzureError("sensitive-provider-diagnostic")
            return SimpleNamespace(token="synthetic-not-a-live-token")

    @contextmanager
    def stream(method, url, **kwargs):
        assert method == "GET" and url == "https://release.example.com/v1/catalog/export"
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        raw = b"x" * (8 * 1024 * 1024 + 1) if mode == "oversize" else b"catalog"
        response = httpx.Response(
            302 if mode == "redirect" else 200,
            headers={"Content-Encoding": "gzip" if mode == "compressed" else "identity"},
            stream=httpx.ByteStream(raw),
        )
        try:
            yield response
        finally:
            response.close()

    monkeypatch.setattr(azure.identity, "ManagedIdentityCredential", Identity)
    monkeypatch.setattr(httpx, "stream", stream)
    if mode == "valid":
        assert fetch_export(source_for(key)) == b"catalog"
    else:
        with pytest.raises(ValueError) as failure:
            fetch_export(source_for(key))
        assert "sensitive-provider-diagnostic" not in str(failure.value)


def test_elapsed_download_expiry_and_changed_approval_preserve_accepted_state(
    monkeypatch,
    tmp_path,
    key,
    catalog,
    now,
):
    from fdai_lifecycle_hub import remote_catalog

    vendor = vendor_for(tmp_path, key, catalog, now)
    raw = vendor.export()[0]
    source = source_for(key)
    engine = create_engine(f"sqlite:///{tmp_path / 'trust.db'}")
    migrate(engine, "lifecycle_hub", lambda c: initialize_trust(c, source))
    target = RemoteCatalog(engine, source, fetch=lambda _: raw)
    approve(target, raw, now)
    before = target.status()
    ticks = iter([0, 2 * 24 * 60 * 60])
    monkeypatch.setattr(remote_catalog.time, "monotonic", lambda: next(ticks))
    with pytest.raises(ValueError, match="expired"):
        target.import_once(actor="operator", now=now)
    assert target.status() == before
    monkeypatch.undo()

    def changed(_):
        payload = json.loads(raw)
        payload["revision"] += 1
        approve(target, canonical_bytes(payload), now)
        return raw

    target.fetch = changed
    with pytest.raises(ValueError, match="changed during download"):
        target.import_once(actor="operator", now=now)
    assert target.status()["minimum_revision"] == 0
    assert target.status()["accepted_sha256"] is None
