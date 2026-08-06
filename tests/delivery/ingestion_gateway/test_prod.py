"""Production document-ingestion composition tests."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest
from starlette.testclient import TestClient

from fdai.delivery.ingestion_gateway import main as gateway_main
from fdai.delivery.ingestion_gateway import prod as prod_module
from fdai.delivery.ingestion_gateway.prod import ProdIngestionConfigError, build_prod_app


def _api_env(**updates: str) -> dict[str, str]:
    env = {
        "FDAI_DATABASE_URL": "postgresql://user:password@db.example.com/fdai",
        "FDAI_DATABASE_ROLE": "fdai_ingestion_api",
        "FDAI_INGESTION_DEPLOYMENT_ROLE": "api",
        "FDAI_ENTRA_TENANT_ID": "00000000-0000-0000-0000-000000000000",
        "FDAI_API_AUDIENCE": "00000000-0000-0000-0000-000000000000",
        "FDAI_RBAC_READERS_GROUP_ID": "reader-group",
        "FDAI_RBAC_CONTRIBUTORS_GROUP_ID": "contributor-group",
        "FDAI_RBAC_APPROVERS_GROUP_ID": "approver-group",
        "FDAI_RBAC_OWNERS_GROUP_ID": "owner-group",
        "FDAI_RBAC_BREAK_GLASS_GROUP_ID": "break-glass-group",
        "FDAI_ADLS_ACCOUNT_NAME": "stfdaidocdev",
        "FDAI_ADLS_ACCOUNT_URL": "https://stfdaidocdev.dfs.core.windows.net",
        "FDAI_EMBEDDING_ENDPOINT": "https://example.openai.azure.com",
        "FDAI_EMBEDDING_DEPLOYMENT": "t1-embedding",
        "FDAI_KAFKA_BOOTSTRAP_SERVERS": "example.servicebus.windows.net:9093",
        "FDAI_DOCUMENT_EVENT_TOPIC": "aw.document.events",
        "FDAI_INGESTION_CORS_ALLOW_ORIGINS": "https://console.example.com",
    }
    env.update(updates)
    return env


@pytest.fixture(autouse=True)
def _stub_database_role_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    async def check(_dsn: str, _expected_role: str) -> None:
        return None

    monkeypatch.setattr(prod_module, "_verify_database_role", check)


def test_prod_factory_lists_all_missing_required_environment() -> None:
    with pytest.raises(ProdIngestionConfigError) as raised:
        build_prod_app({})

    message = str(raised.value)
    assert "FDAI_DATABASE_URL" in message
    assert "FDAI_ADLS_ACCOUNT_URL" in message
    assert "FDAI_DOCUMENT_EVENT_TOPIC" in message
    assert "FDAI_EMBEDDING_DEPLOYMENT" in message


def test_prod_factory_composes_all_runtime_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://127.0.0.1:40342/token")
    monkeypatch.setenv("IDENTITY_HEADER", "synthetic-proof")
    env = _api_env()

    application = build_prod_app(env)

    paths = {route.path for route in application.routes}
    assert "/ingestion/uploads" in paths
    assert "/ingestion/uploads/{upload_id}/handover-draft" in paths
    assert "/documents/search" in paths


def test_prod_api_lifespan_starts_no_worker_loops(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://127.0.0.1:40342/token")
    monkeypatch.setenv("IDENTITY_HEADER", "synthetic-proof")
    env = _api_env()
    first_revision = build_prod_app(env)
    second_revision = build_prod_app(env)

    def reject_background_task(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ingestion API MUST NOT start a worker loop")

    monkeypatch.setattr(gateway_main.asyncio, "create_task", reject_background_task)
    with (
        TestClient(first_revision) as first_client,
        TestClient(second_revision) as second_client,
    ):
        assert first_client.get("/healthz").status_code == 200
        assert second_client.get("/healthz").status_code == 200


def test_prod_api_cohost_rollback_starts_exact_worker_loops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://127.0.0.1:40342/token")
    monkeypatch.setenv("IDENTITY_HEADER", "synthetic-proof")
    application = build_prod_app(
        _api_env(
            FDAI_DATABASE_ROLE="fdai_ingestion_cohost",
            FDAI_INGESTION_COHOST_WORKER="1",
        )
    )
    original_create_task = gateway_main.asyncio.create_task
    created = 0

    async def parked() -> None:
        await asyncio.Event().wait()

    def replace_worker_task(coroutine: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        nonlocal created
        created += 1
        coroutine.close()
        return original_create_task(parked())

    monkeypatch.setattr(gateway_main.asyncio, "create_task", replace_worker_task)
    with TestClient(application) as client:
        assert client.get("/healthz").status_code == 200
        assert created == 3


def test_prod_api_cohost_rollback_rejects_split_database_role() -> None:
    with pytest.raises(ProdIngestionConfigError, match="DATABASE_ROLE"):
        build_prod_app(_api_env(FDAI_INGESTION_COHOST_WORKER="1"))
