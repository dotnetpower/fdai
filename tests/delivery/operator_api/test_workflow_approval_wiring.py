"""Durable workflow approval composition tests."""

from __future__ import annotations

from fdai.core.rbac.resolver import GroupMapping
from fdai.delivery.operator_api.postgres_read_model import (
    PostgresConsoleReadModel,
    PostgresConsoleReadModelConfig,
)
from fdai.delivery.operator_api.production.views import _build_dynamic_views
from fdai.delivery.persistence import PostgresStateStore
from fdai.delivery.persistence.workflow_approval import StateStoreWorkflowApprovalProvider


def _group_mapping() -> GroupMapping:
    return GroupMapping.from_config(
        {
            "rbac": {
                "entra": {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "groups": {
                        "readers": "reader-group",
                        "contributors": "contributor-group",
                        "approvers": "approver-group",
                        "owners": "owner-group",
                        "break_glass": "break-glass-group",
                    },
                }
            }
        },
        environ={},
    )


def test_production_workflow_uses_postgres_approval_store() -> None:
    config = PostgresConsoleReadModelConfig(
        dsn="postgresql://fdai:devonly@127.0.0.1:5432/fdai",
        statement_timeout_ms=1000,
        connect_timeout_s=1,
    )
    wiring = _build_dynamic_views(
        dsn=config.dsn,
        statement_timeout_ms=config.statement_timeout_ms,
        connect_timeout_s=config.connect_timeout_s,
        read_model=PostgresConsoleReadModel(config=config),
        group_mapping=_group_mapping(),
    )

    provider = wiring[-1].orchestrator._approval_provider
    assert isinstance(provider, StateStoreWorkflowApprovalProvider)
    assert isinstance(provider.store, PostgresStateStore)
