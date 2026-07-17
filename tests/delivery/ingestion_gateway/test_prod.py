"""Production document-ingestion composition tests."""

from __future__ import annotations

import pytest

from fdai.delivery.ingestion_gateway.prod import ProdIngestionConfigError, build_prod_app


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
    env = {
        "FDAI_DATABASE_URL": "postgresql://user:password@db.example.com/fdai",
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

    application = build_prod_app(env)

    paths = {route.path for route in application.routes}
    assert "/ingestion/uploads" in paths
    assert "/ingestion/uploads/{upload_id}/handover-draft" in paths
    assert "/documents/search" in paths
