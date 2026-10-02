"""Workflow authoring connects with the direct-driver form of the configured DSN."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from fdai_operator_service import postgres_workflow_authoring
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
    PostgresFamilyStoreUnavailable,
)
from fdai_operator_service.postgres_workflow_authoring import PostgresWorkflowAuthoringStore


@pytest.mark.asyncio
async def test_authoring_store_normalizes_the_sqlalchemy_driver_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted: list[str] = []

    async def refuse_connect(conninfo: str, **_kwargs: Any) -> Any:
        attempted.append(conninfo)
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(
        postgres_workflow_authoring.psycopg.AsyncConnection, "connect", refuse_connect
    )
    store = PostgresFamilyStore(
        PostgresFamilyStoreConfig(dsn="postgresql+psycopg://operator@127.0.0.1:5432/fdai")
    )

    with pytest.raises(PostgresFamilyStoreUnavailable):
        await PostgresWorkflowAuthoringStore(store).delete_binding(
            principal_id="principal-a",
            binding_id="workflow-binding:example",
            idempotency_key="idempotency-a",
            expected_revision="1",
        )

    assert attempted == ["postgresql://operator@127.0.0.1:5432/fdai"]
