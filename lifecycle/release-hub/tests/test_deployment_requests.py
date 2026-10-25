from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from starlette.testclient import TestClient

from fdai_lifecycle_hub.migrations import migrate
from fdai_lifecycle_hub.remote_auth import RemoteAuth
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_release_hub.api import create_app
from fdai_release_hub.database import deployment_requests, metadata
from fdai_release_hub.store import Change, ReleaseStore

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def postgres_engine(loopback_postgres_url):
    url = make_url(loopback_postgres_url)
    if url.port != 5433:
        raise pytest.UsageError("Release request PostgreSQL tests require validation port 5433.")
    schema = "release_requests_" + uuid4().hex
    admin = create_engine(
        url,
        hide_parameters=True,
        connect_args={"connect_timeout": 3, "options": "-cstatement_timeout=5000"},
    )
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 3,
            "options": f"-csearch_path={schema} -cstatement_timeout=5000",
        },
    )
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def store(request, tmp_path):
    target = (
        request.getfixturevalue("postgres_engine")
        if getattr(request, "param", "sqlite") == "postgres"
        else tmp_path / "requests.db"
    )
    store = ReleaseStore(
        target,
        HubSigningKey(Ed25519PrivateKey.generate(), 1),
        clock=lambda: NOW,
    )
    manifest = (Path(__file__).parents[2] / "hub/samples/catalog/releases/1.6.0.json").read_text()
    for revision, action in enumerate(("register", "publish")):
        store.change(
            action,
            "1.6.0",
            Change(
                revision=revision,
                confirmation="1.6.0",
                reason="Synthetic local review",
                manifest=manifest if action == "register" else None,
            ),
        )
    return store


@pytest.fixture
def client(store):
    with TestClient(
        create_app(store), base_url="http://127.0.0.1", client=("127.0.0.1", 50001)
    ) as client:
        yield client


def payload(**changes):
    return {
        "request_id": "a" * 64,
        "subscription_id": SUBSCRIPTION,
        "release_id": "1.6.0",
        "channel": "DEV",
        "region": "eastus",
        "source_commit": "b" * 40,
        "catalog_digest": "c" * 64,
        **changes,
    }


@pytest.mark.parametrize("store", ["sqlite", "postgres"], indirect=True)
def test_persistence_idempotency_and_no_catalog_publication(store, client):
    before = store.export()
    first = client.post("/v1/deployment-requests", json=payload())
    assert first.status_code == 201
    assert first.json() == {
        **payload(),
        "recorded_at": NOW.isoformat(timespec="microseconds"),
        "status": "requested",
        "trust": "self-reported",
    }
    retry = client.post("/v1/deployment-requests", json=payload())
    assert retry.status_code == 200
    assert retry.json() == first.json()
    conflict = client.post("/v1/deployment-requests", json=payload(region="westus"))
    assert conflict.status_code == 409
    reopened = ReleaseStore(store.path, store.key, clock=lambda: NOW, initialize=False)
    with TestClient(
        create_app(reopened), base_url="http://127.0.0.1", client=("127.0.0.1", 50001)
    ) as other:
        assert other.get("/v1/deployment-requests").json() == {
            "requests": [first.json()],
            "limit": 25,
            "offset": 0,
            "has_more": False,
        }
    assert store.export() == before
    assert SUBSCRIPTION.encode() not in before[0]
    assert b"deployment_requests" not in before[0]
    assert store.snapshot()["revision"] == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"request_id": "A" * 64},
        {"request_id": "a" * 63},
        {"request_id": 12},
        {"subscription_id": "00000000-0000-0000-0000-00000000000A"},
        {"subscription_id": "0" * 36},
        {"subscription_id": None},
        {"release_id": "v1.6.0"},
        {"release_id": "01.6.0"},
        {"release_id": "a" * 65},
        {"channel": "development"},
        {"channel": "custom-"},
        {"channel": "custom-Pilot"},
        {"channel": "custom-a--b"},
        {"channel": "custom-" + "a" * 58},
        {"region": "East US"},
        {"region": "east-us"},
        {"region": "x" * 65},
        {"source_commit": "b" * 39},
        {"source_commit": "B" * 40},
        {"catalog_digest": "C" * 64},
        {"catalog_digest": "c" * 65},
        {"tenant_id": SUBSCRIPTION},
        {"credentials": "not-accepted"},
        {"callback": "https://example.com"},
        {"deployment_identity": "not-accepted"},
        {"message": "not-accepted"},
        {"status": "deployed"},
        {"trust": "verified"},
        {"recorded_at": NOW.isoformat()},
    ],
)
def test_invalid_metadata_is_rejected_without_storage(client, changes):
    assert client.post("/v1/deployment-requests", json=payload(**changes)).status_code == 422
    assert client.get("/v1/deployment-requests").json()["requests"] == []


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b"null",
        b"{",
        b'{"request_id":"a","request_id":"b"}',
        b"\xff",
    ],
)
def test_strict_json_and_missing_fields(client, body):
    assert (
        client.post(
            "/v1/deployment-requests", content=body, headers={"Content-Type": "application/json"}
        ).status_code
        == 422
    )


def test_transport_bounds(client):
    endpoint = "/v1/deployment-requests"
    assert client.post(endpoint, content="{}").status_code == 415
    assert (
        client.post(endpoint, json=payload(), headers={"Content-Encoding": "gzip"}).status_code
        == 415
    )
    assert (
        client.post(endpoint, json=payload(), headers={"Content-Length": "-1"}).status_code == 400
    )
    assert (
        client.post(endpoint, json=payload(), headers={"Content-Length": "bad"}).status_code == 400
    )
    assert (
        client.post(
            endpoint, content=" " * 2049, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )
    assert (
        client.post(
            endpoint,
            content=iter([b" " * 1024, b" " * 1025]),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    assert (
        client.post(endpoint, json=payload(), headers={"Origin": "https://example.com"}).status_code
        == 403
    )


def test_eligibility_and_recalled_exact_retry(store, client):
    for changes in ({"release_id": "9.0.0"}, {"channel": "RELEASE"}, {"channel": "custom-pilot"}):
        assert client.post("/v1/deployment-requests", json=payload(**changes)).status_code == 409
    assert client.post("/v1/deployment-requests", json=payload()).status_code == 201
    store.change(
        "recall",
        "1.6.0",
        Change(
            revision=2,
            confirmation="1.6.0",
            reason="Synthetic recall review",
        ),
    )
    assert (
        client.post("/v1/deployment-requests", json=payload(request_id="d" * 64)).status_code == 409
    )
    assert client.post("/v1/deployment-requests", json=payload()).status_code == 200


def test_draft_and_invalid_signature_are_not_eligible(store, client):
    from fdai_release_hub.database import releases

    with store.connect() as db:
        db.execute(releases.update().values(signature="invalid"))
    assert client.post("/v1/deployment-requests", json=payload()).status_code == 503
    with store.connect() as db:
        db.execute(releases.update().values(signature=None, published_at=None))
    assert client.post("/v1/deployment-requests", json=payload()).status_code == 409


def test_list_filter_pagination_and_stable_ties(store, client):
    for request_id in ("a", "b", "c"):
        assert (
            client.post(
                "/v1/deployment-requests", json=payload(request_id=request_id * 64)
            ).status_code
            == 201
        )
    store.clock = lambda: NOW + timedelta(seconds=1)
    other = "00000000-0000-0000-0000-000000000001"
    assert (
        client.post(
            "/v1/deployment-requests", json=payload(request_id="0" * 64, subscription_id=other)
        ).status_code
        == 201
    )
    page = client.get("/v1/deployment-requests?limit=2").json()
    assert [item["request_id"] for item in page["requests"]] == ["0" * 64, "c" * 64]
    assert page["has_more"] is True
    tail = client.get("/v1/deployment-requests?limit=2&offset=2").json()
    assert [item["request_id"] for item in tail["requests"]] == ["b" * 64, "a" * 64]
    assert tail["has_more"] is False
    filtered = client.get(f"/v1/deployment-requests?subscription_id={SUBSCRIPTION}").json()
    assert len(filtered["requests"]) == 3
    assert all(item["subscription_id"] == SUBSCRIPTION for item in filtered["requests"])


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "offset=-1",
        "offset=100001",
        "limit=x",
        "offset=1.0",
        "limit=1&limit=2",
        "secret=anything",
        "subscription_id=not-a-uuid",
    ],
)
def test_invalid_listing_bounds(client, query):
    assert client.get(f"/v1/deployment-requests?{query}").status_code == 422


def test_listing_offsets_cover_storage_capacity(client):
    from fdai_release_hub.deployment_requests import MAX_STORED_REQUESTS

    for offset in (10000, 10025, MAX_STORED_REQUESTS - 1, MAX_STORED_REQUESTS):
        response = client.get(f"/v1/deployment-requests?offset={offset}")
        assert response.status_code == 200
        assert response.json() == {
            "requests": [],
            "limit": 25,
            "offset": offset,
            "has_more": False,
        }
    assert (
        client.get(f"/v1/deployment-requests?offset={MAX_STORED_REQUESTS + 1}").status_code == 422
    )


def test_concurrent_exact_requests_create_one_row(store):
    from fdai_release_hub.deployment_requests import DeploymentRequest, record_request

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: record_request(store, DeploymentRequest(**payload())), range(4))
        )
    assert sum(created for _, created in results) == 1
    assert all(record == results[0][0] for record, _ in results)


def test_storage_capacity_and_unavailable_errors(client, monkeypatch):
    monkeypatch.setattr("fdai_release_hub.deployment_requests.MAX_STORED_REQUESTS", 1)
    assert client.post("/v1/deployment-requests", json=payload()).status_code == 201
    assert client.post("/v1/deployment-requests", json=payload()).status_code == 200
    assert (
        client.post("/v1/deployment-requests", json=payload(request_id="d" * 64)).status_code == 503
    )

    def unavailable(*args):
        raise OSError("Untrusted storage error content.")

    monkeypatch.setattr("fdai_release_hub.api.record_request", unavailable)
    result = client.post("/v1/deployment-requests", json=payload())
    assert result.status_code == 503
    assert result.json() == {"error": "Local storage is unavailable."}
    monkeypatch.setattr("fdai_release_hub.api.list_requests", unavailable)
    assert client.get("/v1/deployment-requests").json() == {
        "error": "Local storage is unavailable."
    }


@pytest.mark.asyncio
async def test_intake_concurrency_and_stream_deadline(store, monkeypatch):
    monkeypatch.setattr("fdai_release_hub.api.MAX_INTAKE_CONCURRENCY", 1)
    transport = httpx.ASGITransport(app=create_app(store), client=("127.0.0.1", 50001))
    started, unblock = asyncio.Event(), asyncio.Event()

    async def slow_body():
        yield b" "
        started.set()
        await unblock.wait()
        yield json.dumps(payload()).encode()

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        pending = asyncio.create_task(
            client.post(
                "/v1/deployment-requests",
                content=slow_body(),
                headers={"Content-Type": "application/json"},
            )
        )
        await asyncio.wait_for(started.wait(), timeout=2)
        try:
            assert (await client.post("/v1/deployment-requests", json=payload())).status_code == 429
        finally:
            unblock.set()
        assert (await pending).status_code == 201
        started.clear()
        unblock.clear()
        monkeypatch.setattr("fdai_release_hub.api.INTAKE_BODY_TIMEOUT_SECONDS", 0.01)
        timed_out = await client.post(
            "/v1/deployment-requests",
            content=slow_body(),
            headers={"Content-Type": "application/json"},
        )
        assert timed_out.status_code == 408
        assert (await client.post("/v1/deployment-requests", json=payload())).status_code == 200


def test_existing_v1_requires_explicit_transactional_upgrade(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'v1.db'}")
    key = HubSigningKey(Ed25519PrivateKey.generate(), 1)
    with engine.begin() as db:
        metadata.create_all(
            db,
            tables=[table for table in metadata.sorted_tables if table is not deployment_requests],
        )
        db.execute(text("INSERT INTO metadata VALUES (:created)"), {"created": NOW.isoformat()})
        db.execute(text("CREATE TABLE release_hub_schema_revision (revision INTEGER PRIMARY KEY)"))
        db.execute(text("INSERT INTO release_hub_schema_revision VALUES (1)"))
    with pytest.raises(ValueError, match="migrate before serving"):
        ReleaseStore(engine, key, initialize=False)
    assert "deployment_requests" not in inspect(engine).get_table_names()

    def failed(db):
        deployment_requests.create(db)
        raise ValueError("Synthetic migration interruption.")

    with pytest.raises(ValueError, match="interruption"):
        migrate(engine, "release_hub", failed)
    assert "deployment_requests" not in inspect(engine).get_table_names()
    upgraded = ReleaseStore(engine, key, clock=lambda: NOW)
    assert upgraded.snapshot()["updated_at"] == NOW.isoformat()
    upgraded.migrate()
    ReleaseStore(engine, key, initialize=False)
    with engine.connect() as db:
        assert db.scalar(text("SELECT revision FROM release_hub_schema_revision")) == 2
        assert db.execute(select(deployment_requests)).all() == []


@pytest.mark.parametrize("store", ["sqlite", "postgres"], indirect=True)
def test_v1_upgrade_preserves_existing_catalog_and_reader_floor(store):
    before = store.export()
    before_snapshot = store.snapshot()
    with store.connect() as db:
        deployment_requests.drop(db)
        db.execute(text("UPDATE release_hub_schema_revision SET revision = 1"))
    with pytest.raises(ValueError, match="migrate before serving"):
        ReleaseStore(store.engine, store.key, initialize=False)
    store.migrate()
    reopened = ReleaseStore(store.engine, store.key, initialize=False, clock=lambda: NOW)
    assert reopened.export() == before
    assert reopened.snapshot() == before_snapshot
    with store.connect() as db:
        db.execute(text("UPDATE release_hub_schema_revision SET revision = 3"))
    with pytest.raises(ValueError, match="migrate before serving"):
        ReleaseStore(store.engine, store.key, initialize=False)
    with pytest.raises(ValueError, match="compatible migration"):
        store.migrate()


def test_public_intake_and_private_operator_listing(store, monkeypatch):
    auth = RemoteAuth(
        profile="remote-development",
        tenant_id=SUBSCRIPTION,
        audience="example-api",
        origin="https://release.example.com",
        spa_client_id="example-spa",
        operator_scope="Release.Manage",
        operator_ids=frozenset({"example-operator"}),
        service_object_id="example-service",
        service_client_id="example-service-client",
    )
    operator = {"oid": "example-operator", "azp": "example-spa", "scp": "Release.Manage"}
    service = {
        "oid": "example-service",
        "azp": "example-service-client",
        "roles": ["Catalog.Read"],
        "idtyp": "app",
    }
    for public in (False, True):
        config = auth.model_copy(update={"public_catalog_export": public})
        app = create_app(store, remote_auth=config)
        monkeypatch.setattr(
            app.state.entra_verifier,
            "verify",
            lambda token: operator if token == "operator" else service,
        )
        with TestClient(app, base_url=config.origin) as client:
            assert client.get("/v1/deployment-requests").status_code == 401
            assert client.head("/v1/deployment-requests").status_code == 401
            assert (
                client.get(
                    "/v1/deployment-requests", headers={"Authorization": "Bearer service"}
                ).status_code
                == 403
            )
            assert (
                client.get(
                    "/v1/deployment-requests", headers={"Authorization": "Bearer operator"}
                ).status_code
                == 200
            )
            anonymous = client.post("/v1/deployment-requests", json=payload())
            assert anonymous.status_code == (201 if public else 401)
            assert client.post("/v1/catalog/renew", json={}).status_code == 401
            assert client.post("/v1/releases/1.6.0/recall", json={}).status_code == 401
            assert client.post("/v1/catalog/export", json={}).status_code == 401
            if public:
                assert client.get("/v1/catalog/export").status_code == 200
                assert SUBSCRIPTION not in client.get("/v1/catalog/export").text
                assert (
                    client.post(
                        "/v1/deployment-requests",
                        json=payload(),
                        headers={"Sec-Fetch-Site": "cross-site"},
                    ).status_code
                    == 403
                )
            else:
                assert (
                    client.post(
                        "/v1/deployment-requests",
                        json=payload(request_id="d" * 64),
                        headers={"Authorization": "Bearer operator"},
                    ).status_code
                    == 201
                )


def test_default_loopback_and_unconfigured_remote_stay_closed(store):
    remote = TestClient(create_app(store), base_url="http://127.0.0.1", client=("192.0.2.1", 1))
    assert remote.post("/v1/deployment-requests", json=payload()).status_code == 403
    unconfigured = TestClient(
        create_app(store, remote_origin="https://release.example.com"),
        base_url="https://release.example.com",
    )
    assert unconfigured.post("/v1/deployment-requests", json=payload()).status_code == 503
