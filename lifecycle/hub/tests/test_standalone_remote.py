"""Exercise each actual remote entrypoint without a peer Hub or directory registration."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from fdai_lifecycle_hub import remote, remote_auth
from fdai_lifecycle_hub.migrations import _versions, require_schema


@pytest.fixture(params=["sqlite", "postgres"])
def engine(request):
    if request.param == "sqlite":
        result = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        yield result
        result.dispose()
        return
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("Run through with-local-test-database.py for PostgreSQL 5433 evidence.")
    url = make_url(value)
    assert url.host in {"127.0.0.1", "localhost", "::1"} and url.port == 5433
    schema = "hub_standalone_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    result = create_engine(
        url, connect_args={"options": f"-csearch_path={schema}"}, hide_parameters=True
    )
    try:
        yield result
    finally:
        result.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.mark.parametrize("kind", ["release", "target"])
def test_migrate_serve_and_ready_without_directory_or_peer(
    monkeypatch, tmp_path: Path, engine, kind: str
):
    origin = "https://standalone.example.com"
    monkeypatch.setenv("FDAI_HUB_REMOTE_CONFIG", json.dumps({"kind": kind, "origin": origin}))
    monkeypatch.setattr(remote, "remote_engine", lambda _: engine)

    def forbidden(*args, **kwargs):
        raise AssertionError("Standalone startup must not initialize directory or catalog clients.")

    monkeypatch.setattr(remote_auth, "EntraVerifier", forbidden)
    monkeypatch.setattr(remote, "RemoteCatalog", forbidden)
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "brand").mkdir()
    (ui / "index.html").write_text("<!doctype html><h1>Standalone Hub</h1>", encoding="utf-8")
    (ui / "assets/app.js").write_text("console.log('synthetic asset');", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["remote", "migrate"])
    remote._run()
    remote._run()
    namespace = "release_hub" if kind == "release" else "lifecycle_hub"
    require_schema(engine, namespace)
    monkeypatch.setattr(sys, "argv", ["remote", "schema"])
    remote._run()
    if kind == "target":
        assert "catalog_trust_state" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM catalog_trust_state")) == 0

    key = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    monkeypatch.setenv("FDAI_HUB_DEVELOPMENT_SIGNING_KEY", key.decode())
    monkeypatch.setattr(sys, "argv", ["remote", "serve", "--ui", str(ui)])
    captured = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.append(app))
    remote._run()
    app = captured.pop()
    with TestClient(app, base_url=origin, client=("192.0.2.1", 1234)) as client:
        assert client.get("/healthz").json()["status"] == "ok"
        assert client.get("/readyz").json() == {"status": "ready"}
        config = client.get("/auth/config").json()
        assert config["profile"] == "remote-unconfigured"
        assert not {"clientId", "authority", "scope"} & config.keys()
        assert client.get("/").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/settings").status_code == 200
        for method, path in [
            ("GET", "/v1/catalog"),
            ("GET", "/v1/installations"),
            ("POST", "/v1/releases/example/publish"),
            ("POST", "/v1/enrollments/example/approve"),
        ]:
            response = client.request(method, path, json={})
            assert response.status_code == 503
            assert response.json() == {"error": "operator_auth_not_configured"}
        assert client.get("/healthz", headers={"Host": "wrong.example.com"}).status_code == 400
        monkeypatch.setattr(
            remote,
            "require_schema",
            lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("synthetic missing schema")),
        )
        assert client.get("/readyz").status_code == 503
        assert client.get("/healthz").status_code == 200


@pytest.mark.parametrize("kind", ["release", "target"])
def test_serving_before_migration_is_rejected(monkeypatch, engine, kind):
    monkeypatch.setenv(
        "FDAI_HUB_REMOTE_CONFIG", json.dumps({"kind": kind, "origin": "https://hub.example.com"})
    )
    monkeypatch.setattr(remote, "remote_engine", lambda _: engine)
    monkeypatch.setattr(sys, "argv", ["remote", "serve"])
    with pytest.raises(ValueError, match="not migrated"):
        remote._run()
    namespace = "release_hub" if kind == "release" else "lifecycle_hub"
    with pytest.raises(ValueError, match="not migrated"):
        require_schema(engine, namespace, allow_pre_native=True)


def test_reader_cutover_precedes_native_floor_upgrade(monkeypatch, tmp_path, engine):
    origin = "https://standalone.example.com"
    monkeypatch.setenv("FDAI_HUB_REMOTE_CONFIG", json.dumps({"kind": "target", "origin": origin}))
    monkeypatch.setattr(remote, "remote_engine", lambda _: engine)
    monkeypatch.setattr(remote, "remote_key", lambda _: Ed25519PrivateKey.generate())
    monkeypatch.setattr(sys, "argv", ["remote", "migrate"])
    remote._run()
    versions = _versions("lifecycle_hub")
    with engine.begin() as connection:
        connection.execute(versions.update().values(revision=5))
    captured = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.append(app))
    monkeypatch.setattr(sys, "argv", ["remote", "serve", "--ui", str(tmp_path)])
    remote._run()
    with TestClient(captured.pop(), base_url=origin) as client:
        assert client.get("/readyz").json() == {"status": "ready"}
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT revision FROM lifecycle_hub_schema_revision")) == 5
            )
        monkeypatch.setattr(sys, "argv", ["remote", "schema"])
        with pytest.raises(ValueError, match="Unsupported Hub schema revision"):
            remote._run()
        monkeypatch.setattr(sys, "argv", ["remote", "migrate"])
        remote._run()
        assert client.get("/readyz").json() == {"status": "ready"}
        require_schema(engine, "lifecycle_hub")
        for unsupported in (4, 7):
            with engine.begin() as connection:
                connection.execute(versions.update().values(revision=unsupported))
            assert client.get("/readyz").status_code == 503
            assert client.get("/healthz").status_code == 200


@pytest.mark.parametrize(
    ("kind", "revision"),
    [("target", 4), ("target", 7), ("release", 2), ("release", 5), ("release", 6)],
)
def test_serving_compatibility_does_not_accept_other_revisions(monkeypatch, engine, kind, revision):
    monkeypatch.setenv(
        "FDAI_HUB_REMOTE_CONFIG", json.dumps({"kind": kind, "origin": "https://hub.example.com"})
    )
    monkeypatch.setattr(remote, "remote_engine", lambda _: engine)
    monkeypatch.setattr(sys, "argv", ["remote", "migrate"])
    remote._run()
    namespace = "lifecycle_hub" if kind == "target" else "release_hub"
    with engine.begin() as connection:
        connection.execute(_versions(namespace).update().values(revision=revision))
    with pytest.raises(ValueError, match="Unsupported Hub schema revision"):
        require_schema(engine, namespace, allow_pre_native=True)
    monkeypatch.setattr(sys, "argv", ["remote", "serve"])
    with pytest.raises(ValueError, match="Unsupported Hub schema revision"):
        remote._run()


@pytest.mark.parametrize("origin", ["http://hub.example.com", "https://hub.example.com/path", ""])
def test_missing_or_invalid_origin_never_becomes_local_mode(origin):
    with pytest.raises(ValueError):
        remote.RemoteConfig(kind="target", origin=origin)
