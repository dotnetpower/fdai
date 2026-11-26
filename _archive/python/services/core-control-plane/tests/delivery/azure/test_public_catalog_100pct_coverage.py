"""Exhaustive 100% coverage verification across ARG, Azure Monitor, AMBA, and Analyzers."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import yaml
from fdai.delivery.azure.arg_catalog_query import (
    ArgCatalogQueryEngine,
    ArgCatalogQueryRequest,
    ArgFilterOperator,
    ArgWherePredicate,
    compile_arg_catalog_query,
)
from fdai.delivery.azure.arg_catalog_relationships import (
    load_arg_relationship_mapping_catalog,
)
from fdai.delivery.azure.arg_public_catalog import load_arg_public_catalog
from fdai.delivery.azure.catalog_analyzers import (
    build_catalog_resource_type_analyzers,
    catalog_analyzer_kind_by_resource_type,
)
from fdai.delivery.azure.catalog_read_investigation import (
    CATALOG_READ_TOOL_SPECS,
    CatalogReadInvestigationDispatcher,
    CatalogReadToolId,
)
from fdai.delivery.azure.catalog_telemetry_mechanisms import (
    CatalogTelemetryMechanism,
    load_causal_mechanism_and_probe_catalog,
)
from fdai.delivery.azure.monitor_catalog_query import (
    MonitorCatalogQueryEngine,
    MonitorCatalogQueryRequest,
    MonitorLogFilterOperator,
    MonitorLogWherePredicate,
    compile_monitor_catalog_query,
)
from fdai.delivery.azure.monitor_log_catalog import load_monitor_log_catalog
from fdai.delivery.azure.resource_type_recipes import (
    all_catalog_kql_metric_queries,
    all_catalog_metrics_api_queries,
    load_resource_type_recipe_catalog,
)
from fdai.delivery.observation_campaign import _LEGACY_OBSERVATION_OWNER_BY_SOURCE
from fdai.delivery.repo_assets import repo_asset_root
from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider
from fdai.shared.providers.observation import LogQueryResult
from fdai.shared.providers.workload_identity import IdentityToken

_ZERO_SUB = "00000000-0000-0000-0000-000000000000"
_NOW = datetime(2026, 11, 1, 4, 0, tzinfo=UTC)


class _StubIdentity:
    async def get_token(self, scope: str) -> IdentityToken:
        return IdentityToken(
            token="stub-token",
            expires_at=datetime(2026, 11, 1, 5, 0, tzinfo=UTC),
            audience=scope,
        )


class _StubLogProvider:
    async def query_log(
        self,
        *,
        query: str,
        window: str,
        max_rows: int = 100,
    ) -> LogQueryResult:
        assert query.startswith("AzureSQLDeadlocks\n")
        assert window == "PT900S"
        assert max_rows == 10
        return LogQueryResult(
            rows=({"_ResourceId": "sql-1", "Message": "deadlock detected"},),
            truncated=False,
        )


def test_arg_public_catalog_covers_all_50_tables_1908_arg_types_and_3405_arm_types() -> None:
    catalog = load_arg_public_catalog()
    assert catalog.total_tables == 50
    assert catalog.total_arg_resource_types == 1908
    assert catalog.total_arm_schema_types == 3405

    for table_name, spec in catalog.tables.items():
        assert f"arg-{table_name}" in _LEGACY_OBSERVATION_OWNER_BY_SOURCE
        req = ArgCatalogQueryRequest(
            table_name=table_name,
            subscription_ids=(_ZERO_SUB,),
            where_predicates=(ArgWherePredicate("name", ArgFilterOperator.NOT_EMPTY),),
            limit=50,
        )
        kql = compile_arg_catalog_query(req, catalog=catalog)
        assert kql.startswith(f"{table_name}\n")
        assert "| take 50" in kql
        assert spec.owner_agent in {"Huginn", "Heimdall", "Njord", "Vidar"}

    for arm_type in catalog.arm_schema_types:
        resolved_tables = catalog.resolve_tables_for_arm_type(arm_type)
        assert resolved_tables
        for tbl in resolved_tables:
            assert tbl in catalog.tables


@pytest.mark.asyncio
async def test_arg_catalog_query_engine_executes_bounded_read_only_query() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/providers/Microsoft.ResourceGraph/resources"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": (
                            f"/subscriptions/{_ZERO_SUB}/resourceGroups/rg-1"
                            "/providers/Microsoft.Compute/virtualMachines/vm-1"
                        ),
                        "name": "vm-1",
                        "type": "microsoft.compute/virtualmachines",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        engine = ArgCatalogQueryEngine(
            http=client,
            identity=_StubIdentity(),
            clock=lambda: _NOW,
        )
        result = await engine.execute(
            ArgCatalogQueryRequest(
                table_name="computeresources",
                subscription_ids=(_ZERO_SUB,),
                resource_types=("Microsoft.Compute/virtualMachineScaleSets/virtualMachines",),
                resource_groups=("rg-1",),
                where_predicates=(
                    ArgWherePredicate(
                        "properties.provisioningState",
                        ArgFilterOperator.EQUALS,
                        ("Succeeded",),
                    ),
                ),
                limit=25,
            )
        )
        assert result.table_name == "computeresources"
        assert result.owner_agent == "Huginn"
        assert result.execution_authority is False
        assert len(result.rows) == 1
        assert result.query_digest.startswith("sha256:")


def test_monitor_log_catalog_covers_all_12_categories_and_867_tables() -> None:
    catalog = load_monitor_log_catalog()
    assert catalog.total_categories == 12
    assert catalog.total_tables == 867

    for table_name in catalog.tables:
        req = MonitorCatalogQueryRequest(
            table_name=table_name,
            lookback_seconds=900,
            resource_id=(
                f"/subscriptions/{_ZERO_SUB}/resourceGroups/rg"
                "/providers/Microsoft.Compute/virtualMachines/vm1"
            ),
            where_predicates=(
                MonitorLogWherePredicate("Category", MonitorLogFilterOperator.NOT_EMPTY),
            ),
            limit=100,
        )
        kql = compile_monitor_catalog_query(req, catalog=catalog)
        assert kql.startswith(f"{table_name}\n")
        assert "| take 100" in kql


@pytest.mark.asyncio
async def test_monitor_catalog_query_engine_executes_against_log_provider() -> None:
    engine = MonitorCatalogQueryEngine(provider=_StubLogProvider())
    res = await engine.execute(
        MonitorCatalogQueryRequest(table_name="azuresqldeadlocks", limit=10),
        now=_NOW,
    )
    assert res.table_name == "AzureSQLDeadlocks"
    assert res.primary_category == "Workloads"
    assert res.execution_authority is False
    assert len(res.rows) == 1


@pytest.mark.asyncio
async def test_156_resource_types_312_metrics_156_kql_350_amba_and_156_analyzers() -> None:
    root = repo_asset_root()
    rt_doc = yaml.safe_load((root / "rule-catalog/vocabulary/resource-types.yaml").read_text())
    canonical_ids = {str(item["id"]).strip() for item in rt_doc["types"]}
    assert len(canonical_ids) == 156

    recipe_cat = load_resource_type_recipe_catalog(root)
    assert recipe_cat.total_resource_types == 156
    assert set(recipe_cat.profiles.keys()) == canonical_ids
    assert recipe_cat.total_platform_metrics == 312
    assert recipe_cat.total_kql_recipes == 156
    assert recipe_cat.total_semantic_definitions == 312
    assert recipe_cat.total_amba_alerts == 350

    api_queries = all_catalog_metrics_api_queries(root)
    kql_queries = all_catalog_kql_metric_queries(root)
    assert len(api_queries) >= 312
    assert len(kql_queries) >= 156

    kind_map = catalog_analyzer_kind_by_resource_type(root)
    assert len(kind_map) == 156
    assert set(kind_map.keys()) == canonical_ids

    sample_point = MetricPoint(
        metric_name="compute_vm.primary_utilization",
        at=_NOW,
        value=95.0,
        labels={"resource_id": "vm-test-1"},
    )
    analyzers = build_catalog_resource_type_analyzers(
        StaticMetricProvider((sample_point,)),
        wall_clock=lambda: _NOW,
        repo_root=root,
    )
    assert len(analyzers) == 156
    vm_analyzer = next(a for a in analyzers if a.resource_kind == "catalog.compute_vm")
    findings = await vm_analyzer.analyze(resource_ref="vm-test-1", window_seconds=300.0)
    assert len(findings) == 1
    assert findings[0].signal == "compute_vm_primary_breach"


def test_24_causal_mechanisms_50_probes_420_relationships_and_20_read_tools() -> None:
    mech_cat = load_causal_mechanism_and_probe_catalog()
    assert mech_cat.total_mechanisms == 24
    assert mech_cat.total_probes == 50
    for mech in CatalogTelemetryMechanism:
        recipe = mech_cat.get_mechanism(mech)
        assert "resource_id" in recipe.kql

    rel_cat = load_arg_relationship_mapping_catalog()
    assert rel_cat.total_mappings == 420
    assert rel_cat.base_mappings_count == 119
    assert rel_cat.extended_mappings_count == 301

    assert len(CATALOG_READ_TOOL_SPECS) == 20
    dispatcher = CatalogReadInvestigationDispatcher()
    summary = dispatcher.coverage_summary()
    assert summary == {
        "arg_tables": 50,
        "arg_resource_types": 1908,
        "arm_schema_types": 3405,
        "arg_relationship_mappings": 420,
        "monitor_log_categories": 12,
        "monitor_log_tables": 867,
        "canonical_resource_types": 156,
        "platform_metric_recipes": 312,
        "kql_telemetry_recipes": 156,
        "semantic_metric_definitions": 312,
        "amba_alert_recipes": 350,
        "causal_telemetry_mechanisms": 24,
        "diagnostic_probes": 50,
        "read_investigation_tools": 20,
    }
    for tool_id in CatalogReadToolId:
        out = dispatcher.compile_direct_query(tool_id)
        assert out["tool_id"] == tool_id.value


def test_catalog_query_compilers_reject_injection_and_unknown_tables_or_columns() -> None:
    arg_cat = load_arg_public_catalog()
    with pytest.raises(KeyError, match="Unknown Azure Resource Graph table"):
        arg_cat.get_table("nonexistenttable")

    with pytest.raises(ValueError, match="not permitted"):
        compile_arg_catalog_query(
            ArgCatalogQueryRequest(
                table_name="resources",
                subscription_ids=(_ZERO_SUB,),
                where_predicates=(
                    ArgWherePredicate("malicious; drop table", ArgFilterOperator.NOT_EMPTY),
                ),
            ),
            catalog=arg_cat,
        )

    mon_cat = load_monitor_log_catalog()
    with pytest.raises(KeyError, match="Unknown Azure Monitor Log Analytics table"):
        mon_cat.get_table("NonExistentLogTable")

    with pytest.raises(ValueError, match="not in allowed_columns"):
        compile_monitor_catalog_query(
            MonitorCatalogQueryRequest(
                table_name="AzureActivity",
                where_predicates=(
                    MonitorLogWherePredicate("InvalidCol", MonitorLogFilterOperator.NOT_EMPTY),
                ),
            ),
            catalog=mon_cat,
        )
