"""System tool suite tests (describe_event, explain_verdict, query_audit, query_inventory)."""

from __future__ import annotations

import pytest
from fdai.core.conversation import (
    DescribeEventTool,
    ExplainVerdictTool,
    Principal,
    QueryAuditTool,
    QueryInventoryTool,
    Role,
    SystemConsoleTool,
    ToolResult,
)
from fdai.core.conversation.system_tools import AuditReader, InventoryProvider
from fdai.core.tiers.t0_deterministic import T0Engine
from fdai.core.tiers.t0_deterministic.engine import AbstainEvaluator
from fdai.core.tiers.t0_deterministic.index import RuleIndex
from fdai.core.trust_router import TrustRouter
from fdai.shared.providers.testing.state_store import InMemoryStateStore


@pytest.fixture
def rules_and_index():
    from pathlib import Path

    import yaml
    from fdai.rule_catalog.schema.action_type import load_action_type_catalog
    from fdai.rule_catalog.schema.resource_type import (
        load_resource_type_registry_from_mapping,
    )
    from fdai.rule_catalog.schema.rule import load_rule_catalog
    from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

    repo_root = Path(__file__).resolve().parents[4]
    registry = PackageResourceSchemaRegistry()
    catalog_root = repo_root / "rule-catalog"
    with (catalog_root / "vocabulary" / "resource-types.yaml").open() as f:
        rt = load_resource_type_registry_from_mapping(yaml.safe_load(f))
    action_types = load_action_type_catalog(catalog_root / "action-types", schema_registry=registry)
    rules = load_rule_catalog(
        catalog_root / "catalog",
        schema_registry=registry,
        resource_types=rt,
        action_types=action_types,
    )
    return list(rules), RuleIndex.build(rules)


# ---------------------------------------------------------------------------
# describe_event
# ---------------------------------------------------------------------------


def test_describe_event_satisfies_protocol(rules_and_index):
    _, index = rules_and_index
    tool = DescribeEventTool(
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index, evaluator=AbstainEvaluator()),
    )
    assert isinstance(tool, SystemConsoleTool)
    assert tool.side_effect_class == "read"
    assert tool.rbac_floor == Role.READER


def test_describe_event_routes_to_t0(rules_and_index):
    _, index = rules_and_index
    tool = DescribeEventTool(
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index, evaluator=AbstainEvaluator()),
    )
    principal = Principal(id="cli", role=Role.READER)
    result = tool.call(
        arguments={
            "resource_type": "object-storage",
            "resource_id": "storage-x",
            "resource_props": {"public_access": True},
        },
        principal=principal,
    )
    assert isinstance(result, ToolResult)
    assert result.data["tier"] == "t0"
    assert result.data["resource_type"] == "object-storage"
    # Abstain evaluator returns None on all candidates -> no findings.
    assert result.data["decision"] == "abstain"
    assert result.data["findings"] == []
    # But we should have candidate rule ids (routing found them).
    assert len(result.data["candidate_rule_ids"]) > 0


def test_describe_event_rejects_bad_arguments(rules_and_index):
    _, index = rules_and_index
    tool = DescribeEventTool(
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index, evaluator=AbstainEvaluator()),
    )
    principal = Principal(id="cli", role=Role.READER)
    r = tool.call(
        arguments={"resource_type": "", "resource_id": "x", "resource_props": {}},
        principal=principal,
    )
    assert r.status == "error"
    r = tool.call(
        arguments={"resource_type": "x", "resource_id": "y", "resource_props": "not-a-dict"},
        principal=principal,
    )
    assert r.status == "error"


def test_describe_event_abstains_on_unknown_resource_type(rules_and_index):
    _, index = rules_and_index
    tool = DescribeEventTool(
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index, evaluator=AbstainEvaluator()),
    )
    principal = Principal(id="cli", role=Role.READER)
    r = tool.call(
        arguments={
            "resource_type": "definitely-not-a-real-type",
            "resource_id": "x",
            "resource_props": {},
        },
        principal=principal,
    )
    # Router abstains -> tool status abstain, no findings.
    assert r.status == "abstain"
    assert r.data["decision"] == "abstain"


# ---------------------------------------------------------------------------
# explain_verdict + query_audit
# ---------------------------------------------------------------------------


async def _seed_audit(store: InMemoryStateStore, entries: list[dict]):
    for e in entries:
        await store.append_audit_entry(e)


def test_explain_verdict_returns_matched_entries():
    import asyncio

    store = InMemoryStateStore()
    asyncio.run(
        _seed_audit(
            store,
            [
                {
                    "event_id": "00000000-0000-0000-0000-000000000001",
                    "action_kind": "control_loop.abstain",
                    "actor": "fdai.core.control_loop",
                    "decision": "abstain",
                    "recorded_at": "2026-07-06T22:00:00Z",
                    "reason": "t0_no_match",
                },
                {
                    "event_id": "00000000-0000-0000-0000-000000000002",
                    "action_kind": "control_loop.abstain",
                    "actor": "fdai.core.control_loop",
                    "decision": "abstain",
                    "recorded_at": "2026-07-06T22:01:00Z",
                    "reason": "t0_no_match",
                },
            ],
        )
    )
    tool = ExplainVerdictTool(audit_reader=store)
    principal = Principal(id="cli", role=Role.READER)
    r = tool.call(
        arguments={"event_id": "00000000-0000-0000-0000-000000000001"},
        principal=principal,
    )
    assert r.status == "ok"
    assert len(r.data["entries"]) == 1
    assert r.data["entries"][0]["event_id"] == "00000000-0000-0000-0000-000000000001"


def test_explain_verdict_rejects_non_uuid():
    store = InMemoryStateStore()
    tool = ExplainVerdictTool(audit_reader=store)
    principal = Principal(id="cli", role=Role.READER)
    r = tool.call(arguments={"event_id": "not-a-uuid"}, principal=principal)
    assert r.status == "error"
    assert "UUID" in r.preview


def test_query_audit_requires_at_least_one_filter():
    store = InMemoryStateStore()
    tool = QueryAuditTool(audit_reader=store)
    principal = Principal(id="cli", role=Role.READER)
    r = tool.call(arguments={}, principal=principal)
    assert r.status == "error"
    assert "at least one filter" in r.preview


def test_query_audit_filters_by_decision_and_actor():
    import asyncio

    store = InMemoryStateStore()
    asyncio.run(
        _seed_audit(
            store,
            [
                {
                    "event_id": "00000000-0000-0000-0000-000000000001",
                    "action_kind": "control_loop.abstain",
                    "actor": "fdai.core.control_loop",
                    "decision": "abstain",
                    "recorded_at": "2026-07-06T22:00:00Z",
                },
                {
                    "event_id": "00000000-0000-0000-0000-000000000002",
                    "action_kind": "executor.shadow",
                    "actor": "fdai.core.executor",
                    "decision": "auto",
                    "recorded_at": "2026-07-06T22:01:00Z",
                },
            ],
        )
    )
    tool = QueryAuditTool(audit_reader=store)
    principal = Principal(id="cli", role=Role.READER)
    r = tool.call(arguments={"decision": "auto"}, principal=principal)
    assert r.status == "ok"
    assert len(r.data["entries"]) == 1
    assert r.data["entries"][0]["decision"] == "auto"


def test_query_audit_bad_since_rejected():
    store = InMemoryStateStore()
    tool = QueryAuditTool(audit_reader=store)
    principal = Principal(id="cli", role=Role.READER)
    r = tool.call(arguments={"since": "not-a-date"}, principal=principal)
    assert r.status == "error"
    assert "RFC 3339" in r.preview


def test_audit_reader_protocol_recognised():
    """InMemoryStateStore satisfies :class:`AuditReader` structurally."""

    store = InMemoryStateStore()
    assert isinstance(store, AuditReader)


# ---------------------------------------------------------------------------
# query_inventory
# ---------------------------------------------------------------------------


class _FakeResource:
    def __init__(self, resource_type: str, id: str, properties: dict):
        self.type = resource_type
        self.id = id
        self.properties = properties


class _FakeBatch:
    def __init__(self, resources):
        self.resources = tuple(resources)


class _FakeInventory:
    def __init__(self, records):
        self._records = records

    async def full_snapshot(self, since: str | None = None):  # noqa: ARG002
        yield _FakeBatch(self._records)

    async def delta(self, cursor: str):  # noqa: ARG002
        yield _FakeBatch(())


def test_query_inventory_returns_filtered_records():
    inv = _FakeInventory(
        [
            _FakeResource("object-storage", "stg-a", {"public_access": True}),
            _FakeResource("object-storage", "stg-b", {"public_access": False}),
            _FakeResource("compute.vm", "vm-1", {}),
        ]
    )
    tool = QueryInventoryTool(inventory=inv)
    principal = Principal(id="cli", role=Role.READER)
    r = tool.call(arguments={"resource_type": "object-storage"}, principal=principal)
    assert r.status == "ok"
    assert len(r.data["records"]) == 2
    assert {rec["id"] for rec in r.data["records"]} == {"stg-a", "stg-b"}


def test_query_inventory_id_substring_filter():
    inv = _FakeInventory(
        [
            _FakeResource("object-storage", "prod-stg-1", {}),
            _FakeResource("object-storage", "dev-stg-1", {}),
        ]
    )
    tool = QueryInventoryTool(inventory=inv)
    principal = Principal(id="cli", role=Role.READER)
    r = tool.call(
        arguments={"resource_type": "object-storage", "id_substring": "prod"},
        principal=principal,
    )
    assert r.status == "ok"
    assert len(r.data["records"]) == 1
    assert r.data["records"][0]["id"] == "prod-stg-1"


def test_query_inventory_empty_result_abstains():
    inv = _FakeInventory([])
    tool = QueryInventoryTool(inventory=inv)
    principal = Principal(id="cli", role=Role.READER)
    r = tool.call(arguments={"resource_type": "object-storage"}, principal=principal)
    assert r.status == "abstain"


def test_inventory_provider_protocol_recognised():
    inv = _FakeInventory([])
    assert isinstance(inv, InventoryProvider)


# ---------------------------------------------------------------------------
# query_inventory - real ResourceRecord shape + resource_group scoping
# ---------------------------------------------------------------------------


def _sql_db(*, rg: str, server: str, db: str, location: str = "koreacentral"):
    """Build a real :class:`ResourceRecord` for one MSSQL database.

    Mirrors what the Azure inventory adapters emit: neutral id derived from
    the ARM path (carrying the resource-group segment) and a ``props`` bag
    that includes the resource ``name`` and ``resourceGroup``.
    """
    from fdai.shared.providers.inventory import ResourceRecord

    arm = (
        f"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/{rg}"
        f"/providers/Microsoft.Sql/servers/{server}/databases/{db}"
    )
    neutral = arm.lower().split("/resourcegroups/", 1)[1]
    neutral = f"resourcegroups/{neutral}"
    return ResourceRecord(
        resource_id=neutral,
        type="sql-database",
        props={"name": db, "location": location, "tags": {}, "resourceGroup": rg},
        provider_ref=arm,
    )


def test_query_inventory_surfaces_props_from_resource_record():
    # Regression: `_drain_inventory` read `.properties`, but the wire contract
    # `ResourceRecord` names the bag `.props` - so the resource name (and every
    # other property) was silently dropped for real backends. The name is
    # exactly what "tell me the MSSQL DB name" needs.
    inv = _FakeInventory([_sql_db(rg="rg-payments", server="sql-a", db="orders")])
    tool = QueryInventoryTool(inventory=inv)
    principal = Principal(id="cli", role=Role.READER)
    r = tool.call(arguments={"resource_type": "sql-database"}, principal=principal)
    assert r.status == "ok"
    assert len(r.data["records"]) == 1
    assert r.data["records"][0]["properties"]["name"] == "orders"
    assert r.data["records"][0]["properties"]["resourceGroup"] == "rg-payments"


def test_query_inventory_mssql_in_resource_group_by_prop():
    # The operator's exact scenario: "list the MSSQL DBs in resource group X".
    inv = _FakeInventory(
        [
            _sql_db(rg="rg-payments", server="sql-a", db="orders"),
            _sql_db(rg="rg-payments", server="sql-a", db="ledger"),
            _sql_db(rg="rg-analytics", server="sql-b", db="events"),
        ]
    )
    tool = QueryInventoryTool(inventory=inv)
    principal = Principal(id="cli", role=Role.READER)
    r = tool.call(
        arguments={"resource_type": "sql-database", "resource_group": "rg-payments"},
        principal=principal,
    )
    assert r.status == "ok"
    names = sorted(rec["properties"]["name"] for rec in r.data["records"])
    assert names == ["ledger", "orders"]
    assert r.data["resource_group"] == "rg-payments"


def test_query_inventory_resource_group_is_case_insensitive():
    inv = _FakeInventory([_sql_db(rg="RG-Payments", server="sql-a", db="orders")])
    tool = QueryInventoryTool(inventory=inv)
    principal = Principal(id="cli", role=Role.READER)
    r = tool.call(
        arguments={"resource_type": "sql-database", "resource_group": "rg-payments"},
        principal=principal,
    )
    assert r.status == "ok"
    assert len(r.data["records"]) == 1


def test_query_inventory_resource_group_matches_neutral_id_segment():
    # A backend that only encodes the group in the neutral id (no prop) still
    # filters, and only on a whole segment - "rg-pay" must NOT match
    # "rg-payments".
    from fdai.shared.providers.inventory import ResourceRecord

    inv = _FakeInventory(
        [
            ResourceRecord(
                resource_id="resourcegroups/rg-payments/providers/x/vaults/v1",
                type="secret-store",
                props={"name": "v1"},
            ),
            ResourceRecord(
                resource_id="resourcegroups/rg-pay/providers/x/vaults/v2",
                type="secret-store",
                props={"name": "v2"},
            ),
        ]
    )
    tool = QueryInventoryTool(inventory=inv)
    principal = Principal(id="cli", role=Role.READER)
    r = tool.call(
        arguments={"resource_type": "secret-store", "resource_group": "rg-pay"},
        principal=principal,
    )
    assert r.status == "ok"
    assert [rec["properties"]["name"] for rec in r.data["records"]] == ["v2"]


def test_query_inventory_resource_group_no_match_abstains():
    inv = _FakeInventory([_sql_db(rg="rg-payments", server="sql-a", db="orders")])
    tool = QueryInventoryTool(inventory=inv)
    principal = Principal(id="cli", role=Role.READER)
    r = tool.call(
        arguments={"resource_type": "sql-database", "resource_group": "rg-nonexistent"},
        principal=principal,
    )
    assert r.status == "abstain"
    assert r.data["records"] == []
