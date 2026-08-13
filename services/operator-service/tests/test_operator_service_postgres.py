"""Focused PostgreSQL projection parity tests for Operator Service."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai_operator_service.postgres import (
    PostgresOperatorReadModel,
    PostgresOperatorReadModelConfig,
    _group_incident_rows,
    _psycopg_dsn,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from fdai_operator_service.postgres_iam import PostgresIamAdapters
from fdai_operator_service.postgres_sql import (
    AGENT_INVENTORY_ACTIVITY_SQL,
    AGENT_OBSERVATION_ACTIVITY_SQL,
    AGENT_ONTOLOGY_ACTIVITY_SQL,
    AGENT_READ_ACTIVITY_SQL,
    AUDIT_PAGE_SQL,
    HIL_COUNT_SQL,
    HIL_PAGE_SQL,
    INCIDENT_PAGE_SQL,
    KPI_SAMPLE_SQL,
    LLM_USAGE_CONVERSATIONS_SQL,
    LLM_USAGE_RECORDS_SQL,
    LLM_USAGE_SUMMARIES_SQL,
)
from fdai_operator_service.routes import _sse_frame
from fdai_service_contracts import (
    AgentActivityQuery,
    AuditQuery,
    HilQueueQuery,
    IncidentAttentionQuery,
    IncidentQuery,
)

_NOW = datetime(2026, 8, 8, tzinfo=UTC)


class ReadinessPostgresFamilyStore(PostgresFamilyStore):
    """Capture the bounded readiness statement without opening PostgreSQL."""

    def __init__(self, row: dict[str, object]) -> None:
        super().__init__(
            PostgresFamilyStoreConfig(
                dsn="postgresql://example.invalid/db",
                role="fdai_operator",
            )
        )
        self.row = row
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        self.calls.append((statement, parameters))
        return [self.row]


class ProjectionPostgresFamilyStore(PostgresFamilyStore):
    """Return one Settings projection without opening PostgreSQL."""

    def __init__(self, payload: dict[str, object]) -> None:
        super().__init__(
            PostgresFamilyStoreConfig(
                dsn="postgresql://example.invalid/db",
                role="fdai_operator",
            )
        )
        self.payload = payload

    async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
        assert (family, operation) == ("iam", "model-settings")
        return self.payload


def test_sqlalchemy_psycopg_dsn_is_normalized_for_direct_driver_use() -> None:
    assert _psycopg_dsn("postgresql+psycopg://user@example.invalid/db") == (
        "postgresql://user@example.invalid/db"
    )
    assert _psycopg_dsn("postgresql://user@example.invalid/db") == (
        "postgresql://user@example.invalid/db"
    )


@pytest.mark.parametrize(
    "dsn",
    ["postgresql+psycopg://", "postgresql://", "postgres://"],
)
@pytest.mark.parametrize(
    "config_type",
    [PostgresOperatorReadModelConfig, PostgresFamilyStoreConfig],
)
def test_postgres_configs_reject_targetless_dsn(
    dsn: str,
    config_type: type[PostgresOperatorReadModelConfig] | type[PostgresFamilyStoreConfig],
) -> None:
    with pytest.raises(ValueError, match="MUST include a connection target"):
        config_type(dsn)


@pytest.mark.asyncio
async def test_operator_readiness_verifies_role_and_privileges_without_durable_write() -> None:
    store = ReadinessPostgresFamilyStore({"ready": True})

    assert await store.probe_readiness() is True

    statement, parameters = store.calls[-1]
    assert parameters == {"expected_role": "fdai_operator"}
    for fragment in (
        "current_user = %(expected_role)s",
        "NOT login_role.rolsuper",
        "NOT login_role.rolcreaterole",
        "NOT login_role.rolcreatedb",
        "NOT login_role.rolreplication",
        "NOT login_role.rolbypassrls",
        "NOT pg_has_role(current_user, 'pg_read_all_data', 'MEMBER')",
        "NOT pg_has_role(current_user, 'pg_write_all_data', 'MEMBER')",
        "has_table_privilege(current_user, 'audit_log', 'SELECT')",
        "has_table_privilege(current_user, 'state_kv', 'SELECT')",
        "has_table_privilege(current_user, 'state_kv', 'INSERT')",
        "has_table_privilege(current_user, 'state_kv', 'UPDATE')",
        "NOT has_table_privilege(current_user, 'audit_log', 'INSERT')",
        "NOT has_table_privilege(current_user, 'audit_log', 'UPDATE')",
        "NOT has_table_privilege(current_user, 'state_kv', 'DELETE')",
        "has_table_privilege(current_user, 'llm_invocation', 'SELECT')",
        "NOT has_table_privilege(current_user, 'llm_invocation', 'INSERT')",
        "NOT has_table_privilege(current_user, 'llm_invocation', 'UPDATE')",
        "NOT has_table_privilege(current_user, 'llm_invocation', 'DELETE')",
        "has_table_privilege(current_user, 'inventory_snapshot', 'SELECT')",
        "NOT has_table_privilege(current_user, 'inventory_snapshot', 'INSERT,UPDATE,DELETE')",
        "has_table_privilege(current_user, 'inventory_snapshot_resource', 'SELECT')",
        "'inventory_snapshot_resource', 'INSERT,UPDATE,DELETE'",
        "has_table_privilege(current_user, 'inventory_snapshot_link', 'SELECT')",
        "'inventory_snapshot_link', 'INSERT,UPDATE,DELETE'",
        "NOT has_schema_privilege(current_user, 'public', 'CREATE')",
    ):
        assert fragment in statement
    for mutation in ("INSERT INTO", "UPDATE state_kv", "DELETE FROM"):
        assert mutation not in statement


@pytest.mark.asyncio
async def test_operator_readiness_rejects_role_or_privilege_failure() -> None:
    store = ReadinessPostgresFamilyStore({"ready": False})

    assert await store.probe_readiness() is False


@pytest.mark.asyncio
async def test_model_projection_injects_principal_capability_at_nested_contract() -> None:
    adapters = PostgresIamAdapters(
        ProjectionPostgresFamilyStore({"web_search": {"available": True}})
    )

    projection = await adapters.projection(
        "principal-1",
        can_manage_web_search=True,
    )

    assert projection["web_search"] == {"available": True, "can_manage": True}
    assert "can_manage_web_search" not in projection


def _audit_row(
    seq: int,
    *,
    correlation_id: str = "corr-1",
    action_kind: str = "control.stage",
    entry: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "seq": seq,
        "event_id": "00000000-0000-0000-0000-000000000001",
        "correlation_id": correlation_id,
        "actor": "operator-test",
        "action_kind": action_kind,
        "mode": "shadow",
        "entry": dict(entry or {}),
        "previous_hash": f"hash-{seq - 1}",
        "entry_hash": f"hash-{seq}",
        "created_at": _NOW,
    }


class StubPostgresReadModel(PostgresOperatorReadModel):
    """Return deterministic rows while recording SQL parameter boundaries."""

    def __init__(self) -> None:
        super().__init__(PostgresOperatorReadModelConfig(dsn="postgresql://example.invalid/db"))
        self.calls: list[tuple[str, Mapping[str, object]]] = []
        self.audit_rows: list[dict[str, object]] = []
        self.hil_rows: list[dict[str, object]] = []
        self.incident_rows: list[dict[str, object]] = []
        self.llm_summary_rows: list[dict[str, object]] = []
        self.llm_conversation_rows: list[dict[str, object]] = []
        self.llm_record_rows: list[dict[str, object]] = []
        self.inventory_activity_rows: list[dict[str, object]] = []
        self.ontology_activity_rows: list[dict[str, object]] = []
        self.read_activity_rows: list[dict[str, object]] = []
        self.observation_activity_rows: list[dict[str, object]] = []

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        self.calls.append((statement, parameters))
        if statement == AUDIT_PAGE_SQL:
            return self.audit_rows
        if statement == KPI_SAMPLE_SQL:
            return self.audit_rows
        if statement == HIL_COUNT_SQL:
            return [{"total_count": len(self.hil_rows)}]
        if statement == HIL_PAGE_SQL:
            return self.hil_rows
        if statement == INCIDENT_PAGE_SQL:
            return self.incident_rows
        if statement == LLM_USAGE_SUMMARIES_SQL:
            return self.llm_summary_rows
        if statement == LLM_USAGE_CONVERSATIONS_SQL:
            return self.llm_conversation_rows
        if statement == LLM_USAGE_RECORDS_SQL:
            return self.llm_record_rows
        if statement == AGENT_INVENTORY_ACTIVITY_SQL:
            return self.inventory_activity_rows
        if statement == AGENT_ONTOLOGY_ACTIVITY_SQL:
            return self.ontology_activity_rows
        if statement == AGENT_READ_ACTIVITY_SQL:
            return self.read_activity_rows
        if statement == AGENT_OBSERVATION_ACTIVITY_SQL:
            return self.observation_activity_rows
        raise AssertionError("unexpected SQL statement")


@pytest.mark.asyncio
async def test_agent_activity_reads_each_durable_source_with_bounded_limits() -> None:
    model = StubPostgresReadModel()
    model.inventory_activity_rows = [
        {
            "id": "attempt-1",
            "status": "active",
            "source": "azure-resource-graph",
            "started_at": _NOW,
            "completed_at": _NOW,
            "failure_code": None,
            "resource_count": 2,
            "link_count": 1,
        }
    ]

    payload = (await model.list_agent_activity(AgentActivityQuery(limit=25))).to_dict()

    assert payload["items"][0]["kind"] == "inventory.scan"
    assert payload["items"][0]["evidence_count"] == 3
    inventory_call = next(call for call in model.calls if call[0] == AGENT_INVENTORY_ACTIVITY_SQL)
    read_call = next(call for call in model.calls if call[0] == AGENT_READ_ACTIVITY_SQL)
    assert inventory_call[1] == {"limit": 25}
    assert read_call[1] == {"limit": 25}
    assert "get_resource_state" in AGENT_READ_ACTIVITY_SQL
    assert "operation_class' = 'resource_state'" in AGENT_READ_ACTIVITY_SQL
    assert "read-investigation-latency:%%" in AGENT_READ_ACTIVITY_SQL


@pytest.mark.asyncio
async def test_audit_query_is_parameterized_paginated_and_redacted() -> None:
    model = StubPostgresReadModel()
    model.audit_rows = [
        _audit_row(
            3,
            entry={
                "token": "secret-value",
                "client-secret": "also-hidden",
                "nested": {"password": "hidden"},
            },
        ),
        _audit_row(2),
    ]
    attack = "corr' OR TRUE --"

    page = await model.list_audit(AuditQuery(limit=1, correlation_id=attack))

    assert page.next_cursor == "3"
    assert page.items[0]["entry"] == {
        "token": "[REDACTED]",
        "client-secret": "[REDACTED]",
        "nested": {"password": "[REDACTED]"},
    }
    statement, parameters = model.calls[0]
    assert attack not in statement
    assert parameters["correlation_id"] == attack
    assert parameters["fetch"] == 2


@pytest.mark.asyncio
async def test_audit_projection_normalizes_null_string_correlation() -> None:
    model = StubPostgresReadModel()
    model.audit_rows = [_audit_row(1, correlation_id="None")]

    page = await model.list_audit(AuditQuery(limit=1))

    assert page.items[0]["correlation_id"] is None


@pytest.mark.asyncio
async def test_hil_reader_gets_count_only_and_approver_gets_redacted_detail() -> None:
    model = StubPostgresReadModel()
    model.hil_rows = [
        {
            "total_count": 1,
            "updated_at": _NOW,
            "value": {
                "approval_id": "approval-1",
                "parked_at": _NOW.isoformat(),
                "idempotency_key": "idem-1",
                "action": {
                    "event_id": "00000000-0000-0000-0000-000000000001",
                    "action_type": "compute.restart",
                    "target_resource_ref": "resource-1",
                    "credential": "must-not-leak",
                },
            },
        }
    ]

    count_only = await model.list_hil_queue(
        HilQueueQuery(limit=50, search=None, include_details=False)
    )
    details = await model.list_hil_queue(
        HilQueueQuery(limit=50, search="resource-1", include_details=True)
    )

    assert count_only.to_dict(include_details=False) == {
        "items": [],
        "total": 1,
        "detail_level": "count_only",
    }
    assert details.items[0]["target_resource_ref"] == "resource-1"
    assert "credential" not in details.items[0]
    detail_call = next(call for call in model.calls if call[0] == HIL_PAGE_SQL)
    assert detail_call[1]["search"] == "resource-1"
    assert detail_call[1]["search_pattern"] == "%resource-1%"


@pytest.mark.asyncio
async def test_malformed_authoritative_hil_row_fails_closed() -> None:
    model = StubPostgresReadModel()
    model.hil_rows = [{"total_count": 1, "value": {"approval_id": "incomplete"}}]

    with pytest.raises(RuntimeError, match="HIL row is malformed"):
        await model.list_hil_queue(HilQueueQuery(limit=50, search=None, include_details=True))


@pytest.mark.asyncio
async def test_kpi_uses_bounded_sample_and_authoritative_hil_count() -> None:
    model = StubPostgresReadModel()
    model.audit_rows = [
        _audit_row(1, action_kind="rule.evaluate", entry={"outcome": "hil", "tier": "T0"})
    ]
    model.hil_rows = [{"value": {}}]

    payload = (await model.dashboard_metrics()).to_dict()

    assert payload["event_count"] == 1
    assert payload["hil_pending"] == 1
    assert payload["by_tier"] == {"t0": 1}
    kpi_call = next(call for call in model.calls if call[0] == KPI_SAMPLE_SQL)
    assert kpi_call[1]["limit"] == 500


@pytest.mark.asyncio
async def test_llm_usage_projects_measured_tokens_without_price_fields() -> None:
    model = StubPostgresReadModel()
    model.llm_summary_rows = [
        {
            "group_kind": kind,
            "group_key": key,
            "invocations": invocations,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
        }
        for kind, key, invocations, prompt, completion in (
            ("total", "total", 2, 30, 12),
            ("chat", "chat", 1, 10, 5),
            ("scope", "control_plane", 1, 20, 7),
            ("scope", "operator_chat", 1, 10, 5),
            ("model", "model-a", 2, 30, 12),
            ("chat_model", "model-a", 1, 10, 5),
            ("mode", "shadow", 2, 30, 12),
            ("hour", "2026-08-08T00:00:00Z", 2, 30, 12),
            ("day", "2026-08-08", 2, 30, 12),
            ("month", "2026-08", 2, 30, 12),
        )
    ]
    model.llm_conversation_rows = [
        {
            "group_key": "corr-1",
            "invocations": 2,
            "prompt_tokens": 30,
            "completion_tokens": 12,
            "conversation_count": 1,
        }
    ]
    model.llm_record_rows = [
        {
            "occurred_at": _NOW,
            "correlation_id": "corr-1",
            "capability_id": "narrator",
            "model_key": "model-a",
            "tier": "narrator",
            "mode": "shadow",
            "usage_scope": "operator_chat",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "record_count": 2,
        }
    ]

    payload = (await model.llm_usage(_NOW, _NOW.replace(day=9))).to_dict()

    assert payload["invocations"] == 2
    assert payload["total"]["total_tokens"] == 42
    assert payload["chat"]["total_tokens"] == 15
    assert payload["by_conversation"][0]["key"] == "corr-1"
    assert payload["records"][0]["total_tokens"] == 15
    assert payload["record_count"] == 2
    assert "cost" not in payload["total"]
    for statement in (
        LLM_USAGE_SUMMARIES_SQL,
        LLM_USAGE_CONVERSATIONS_SQL,
        LLM_USAGE_RECORDS_SQL,
    ):
        call = next(item for item in model.calls if item[0] == statement)
        assert call[1]["range_start"] == _NOW


@pytest.mark.asyncio
async def test_incident_page_and_attention_replay_use_durable_sequence() -> None:
    model = StubPostgresReadModel()
    row = _audit_row(
        7,
        entry={
            "kind": "incident.open",
            "incident_id": "INC-1",
            "severity": "high",
            "state": "open",
            "opened_at": _NOW.isoformat(),
            "correlation_keys": ["resource:example-app"],
        },
    )
    row.update(
        {
            "normalized_correlation_id": "corr-1",
            "group_last_seq": 7,
            "group_history_count": 1,
            "snapshot_seq": 7,
        }
    )
    model.incident_rows = [row]

    page = await model.list_incidents(IncidentQuery(status="active", limit=50))
    initial = await model.incident_attention(IncidentAttentionQuery(after_seq=None, limit=50))
    replayed = await model.incident_attention(IncidentAttentionQuery(after_seq=7, limit=50))

    assert page.items[0]["title"] == "Resource example-app"
    assert page.items[0]["status"] == "open"
    assert initial is not None
    assert initial.sequence == 7
    assert initial.to_dict()["incidents"][0]["incident_id"] == "INC-1"
    assert replayed is None
    assert _sse_frame(initial).startswith(
        b'id: 7\nevent: incident-attention\ndata: {"event":"incident_attention.snapshot"'
    )


def test_incident_projection_rejects_null_string_correlation_sentinels() -> None:
    valid = {"normalized_correlation_id": " corr-1 "}

    grouped = _group_incident_rows(
        [
            {"normalized_correlation_id": None},
            {"normalized_correlation_id": ""},
            {"normalized_correlation_id": "None"},
            {"normalized_correlation_id": "null"},
            valid,
        ]
    )

    assert grouped == [[valid]]
    assert "LOWER(BTRIM(normalized_correlation_id)) NOT IN ('none', 'null')" in (INCIDENT_PAGE_SQL)


@pytest.mark.asyncio
async def test_trace_and_rca_preserve_frozen_envelopes() -> None:
    model = StubPostgresReadModel()
    model.audit_rows = [
        _audit_row(
            2,
            action_kind="risk_gate.shadow_authority",
            entry={"stage": "gate", "decision": "auto", "rollback_reference": "pr-7"},
        ),
        _audit_row(
            1,
            action_kind="rca.hypothesis",
            entry={
                "rca_outcome": "grounded",
                "rca_tier": "t0",
                "rca_cause": "public access open",
                "rca_confidence": 0.95,
                "rca_citations": [{"kind": "rule", "ref": "storage.public-access"}],
            },
        ),
    ]

    trace = await model.get_rule_fire_trace("corr-1")
    rca = await model.get_rca("corr-1")

    assert trace is not None
    assert trace.to_dict()["terminal_stage"] == "gate"
    assert rca is not None
    assert rca.to_dict()["hypotheses"][0]["tier"] == "t0"
    assert rca.to_dict()["response"]["verdict"] == "auto"
