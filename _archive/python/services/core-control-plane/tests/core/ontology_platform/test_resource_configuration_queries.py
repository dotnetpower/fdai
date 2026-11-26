"""Configuration comparison requires scoped, complete, time-aligned observed history."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
)
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.core.ontology_platform.resource_configuration_queries import (
    RESOURCE_CONFIGURATION_FUNCTION_NAME,
    compare_resource_configuration,
    resource_configuration_changes_function,
    resource_configuration_function_type,
)
from fdai.core.ontology_platform.resource_configuration_snapshots import (
    project_configuration_snapshot,
)
from fdai.core.ontology_platform.topology_history import (
    TopologyGraphAt,
    TopologyObjectRevision,
    TopologyRevisionBatch,
    graph_at,
)
from fdai.shared.contracts.models import CeilingRole, OntologyRelease
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord

NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)
BEFORE = NOW - timedelta(hours=1)
_MODEL = {
    "model_name": "example-model",
    "model_version": "1",
    "sku_name": "Standard",
    "capacity_units": 100,
    "current_capacity_units": 100,
    "capacity_transitioning": False,
    "capacity_tpm": 6000,
    "capacity_tpm_source": "properties.rateLimits",
}


def _resource(
    resource_id: str = "resource-example",
    *,
    updates: dict[str, Any] | None = None,
    model: bool = True,
) -> OntologyObjectRecord:
    payload = {**(_MODEL if model else {}), **(updates or {})}
    return OntologyObjectRecord(
        id=resource_id,
        object_type="Resource",
        properties={
            "id": resource_id,
            "name": resource_id,
            "type": "llm-model-deployment" if model else "compute.vm",
            "location": "example-region",
            "properties": payload,
        },
    )


def _release() -> OntologyRelease:
    return build_ontology_release(function_types=(resource_configuration_function_type(),))


def _scope(
    resources: tuple[OntologyObjectRecord, ...],
    release: OntologyRelease,
    *,
    complete: bool = True,
    redacted: bool = False,
) -> SecuredObjectSetQueryResult:
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=1000,
    )
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(objects=resources, source_complete=complete),
        concrete_types=("Resource",),
        truncated=False,
    )
    return SecuredObjectSetQueryResult(
        materialization=materialization,
        receipt=SecuredObjectSetQueryReceipt(
            ontology_release=release.ref(),
            projected_result_digest=_projected_result_digest(materialization),
            purpose="operations-review",
            caller_role=CeilingRole.READER,
            observation_cutoff=NOW,
            as_of_skew_seconds=0,
            returned_object_count=len(resources),
            returned_link_count=0,
            source_complete=complete,
            complete=complete,
            truncated=False,
            redactions=ObjectSetRedactionSummary(
                objects_with_redactions=int(redacted),
                redacted_identity_count=0,
                access_scope_count=0,
                purpose_binding_count=0,
                undeclared_property_count=0,
                links_with_redactions=0,
                redacted_link_property_count=0,
                removed_link_count=0,
            ),
        ),
    )


def _history(
    records: tuple[OntologyObjectRecord, ...],
    release: OntologyRelease,
    *,
    as_of: datetime,
    complete: bool = True,
) -> TopologyGraphAt:
    return graph_at(
        (_batch(records, release, as_of=as_of, complete=complete),),
        as_of=as_of,
        known_at=NOW,
    )


def _batch(
    records: tuple[OntologyObjectRecord, ...],
    release: OntologyRelease,
    *,
    as_of: datetime,
    complete: bool = True,
) -> TopologyRevisionBatch:
    return TopologyRevisionBatch(
        revision_id="revision-before" if as_of == BEFORE else "revision-after",
        provider_generation_ref="example-generation",
        effective_at=as_of,
        recorded_at=as_of,
        complete_snapshot=complete,
        object_revisions=tuple(
            TopologyObjectRevision.upsert(
                record,
                effective_at=as_of,
                recorded_at=as_of,
                evidence_ref=f"inventory:{record.id}",
            )
            for record in records
        ),
        ontology_release_digest=release.digest,
        source_receipt_digest="sha256:" + "b" * 64,
    )


def _compare(
    before: OntologyObjectRecord,
    after: OntologyObjectRecord,
    *,
    selected: tuple[OntologyObjectRecord, ...] | None = None,
) -> dict[str, Any]:
    release = _release()
    scope = _scope(selected or (after,), release)
    return compare_resource_configuration(
        query_result=scope,
        before=project_configuration_snapshot(
            query_result=scope,
            view=_history((before,), release, as_of=BEFORE),
        ),
        after=project_configuration_snapshot(
            query_result=scope,
            view=_history((after,), release, as_of=NOW),
        ),
    )


def test_capacity_drop_preserves_desired_current_and_authoritative_tpm() -> None:
    before = _resource()
    after = _resource(updates={"capacity_units": 20, "capacity_transitioning": True})
    result = _compare(before, after)
    row = result["rows"][0]["values"]
    assert result["complete"] is True
    assert row["comparison_status"] == "changed"
    assert row["changed_fields"] == ["capacity_transitioning", "capacity_units"]
    assert row["before"]["capacity_units"] == 100
    assert row["after"]["capacity_units"] == 20
    assert row["after"]["current_capacity_units"] == 100
    assert row["before"]["capacity_tpm"] == row["after"]["capacity_tpm"] == 6000
    assert row["after"]["capacity_tpm_source"] == "properties.rateLimits"
    assert "if demand exceeds" in row["potential_implications"][0]
    assert row["observed_429"] == row["observed_500"] == "unknown"
    assert row["observed_latency_effect"] == "unknown"
    assert row["causal_claim_supported"] is row["execution_authority"] is False


@pytest.mark.parametrize("source", [None, "capacity_units", "inferred_tpm"])
def test_tpm_never_comes_from_capacity_unit_arithmetic(source: str | None) -> None:
    record = _resource(updates={"capacity_tpm": 100_000, "capacity_tpm_source": source})
    result = _compare(record, record)
    row = result["rows"][0]["values"]
    assert result["complete"] is False
    assert row["comparison_status"] == "unknown"
    assert row["before"]["capacity_units"] == 100
    assert row["before"]["capacity_tpm"] is None
    assert row["after"]["capacity_tpm_source"] is None


@pytest.mark.parametrize(
    "updates",
    [
        {"model_name": "example-other-model"},
        {"model_version": "2"},
        {"sku_name": "Provisioned"},
        {"capacity_tpm": 321},
        {"current_capacity_units": 50, "capacity_transitioning": True},
    ],
)
def test_all_reviewed_model_fields_report_actual_before_and_after(updates: dict[str, Any]) -> None:
    row = _compare(_resource(), _resource(updates=updates))["rows"][0]["values"]
    assert row["comparison_status"] == "changed"
    for field, value in updates.items():
        assert row["after"][field] == value
        assert field in row["changed_fields"]


def test_clock_and_unreviewed_secret_payload_churn_is_not_configuration_drift() -> None:
    before = _resource(updates={"observed_at": BEFORE.isoformat(), "secret": "hidden-before"})
    after = _resource(updates={"observed_at": NOW.isoformat(), "secret": "hidden-after"})
    row = _compare(before, after)["rows"][0]["values"]
    assert row["comparison_status"] == "unchanged_reviewed_fields"
    assert row["before_digest"] == row["after_digest"]
    assert row["changed_fields"] == []
    assert "hidden-" not in json.dumps(row)


@pytest.mark.parametrize(
    "updates",
    [
        {"capacity_units": True},
        {"capacity_units": -1},
        {"model_name": "x" * 257},
        {"capacity_units": 20, "capacity_transitioning": False},
    ],
)
def test_invalid_or_conflicting_summary_fields_remain_unknown(updates: dict[str, Any]) -> None:
    record = _resource(updates=updates)
    row = _compare(record, record)["rows"][0]["values"]
    assert row["comparison_status"] == "unknown"
    assert row["reason"] == "configuration_fields_unavailable"


def test_generic_comparison_exposes_only_reviewed_field_digests() -> None:
    before = _resource(model=False, updates={"sku_name": "ExampleSmall", "secret": "hidden-before"})
    after = _resource(model=False, updates={"sku_name": "ExampleLarge", "secret": "hidden-after"})
    row = _compare(before, after)["rows"][0]["values"]
    serialized = json.dumps(row)
    assert row["comparison_status"] == "changed"
    assert row["changed_fields"] == ["sku_name"]
    assert row["before"]["sku_name"]["digest"].startswith("sha256:")
    assert "ExampleSmall" not in serialized and "ExampleLarge" not in serialized
    assert "hidden-" not in serialized


def test_generic_field_missing_on_one_side_cannot_prove_no_change() -> None:
    result = _compare(
        _resource(model=False, updates={"sku_name": "ExampleSmall"}),
        _resource(model=False),
    )
    row = result["rows"][0]["values"]
    assert result["complete"] is False
    assert row["comparison_status"] == "unknown"
    assert row["missing_fields"] == ["sku_name"]


def test_unverified_current_type_cannot_unlock_historical_model_properties() -> None:
    record = _resource()
    record = replace(
        record,
        properties={key: value for key, value in record.properties.items() if key != "type"},
    )
    row = _compare(record, record)["rows"][0]["values"]
    assert row["comparison_status"] == "unknown"
    assert row["reason"] == "configuration_identity_mismatch"
    assert row["before"] is row["after"] is None


def test_unselected_historical_resource_never_appears_in_configuration_output() -> None:
    release = _release()
    target = _resource()
    hidden = _resource("resource-not-authorized", updates={"model_name": "hidden-model"})
    scope = _scope((target,), release)
    result = compare_resource_configuration(
        query_result=scope,
        before=project_configuration_snapshot(
            query_result=scope,
            view=_history((target, hidden), release, as_of=BEFORE),
        ),
        after=project_configuration_snapshot(
            query_result=scope,
            view=_history((target, hidden), release, as_of=NOW),
        ),
    )
    assert len(result["rows"]) == 1
    serialized = json.dumps(result)
    assert "resource-not-authorized" not in serialized
    assert "hidden-model" not in serialized


@pytest.mark.parametrize(
    "defect",
    ["baseline_missing", "after_missing", "before_incomplete", "after_incomplete", "release"],
)
def test_missing_or_incomplete_history_is_unknown_not_no_change(defect: str) -> None:
    release = _release()
    record = _resource()
    before = _history(() if defect == "baseline_missing" else (record,), release, as_of=BEFORE)
    after = _history(() if defect == "after_missing" else (record,), release, as_of=NOW)
    if defect == "before_incomplete":
        before = replace(before, complete=False)
    if defect == "after_incomplete":
        after = replace(after, graph=replace(after.graph, truncated=True))
    if defect == "release":
        before = replace(before, ontology_release_digests=("sha256:" + "c" * 64,))
    scope = _scope((record,), release)
    result = compare_resource_configuration(
        query_result=scope,
        before=project_configuration_snapshot(query_result=scope, view=before),
        after=project_configuration_snapshot(query_result=scope, view=after),
    )
    assert result["complete"] is False
    assert result["rows"][0]["values"]["comparison_status"] == "unknown"


@pytest.mark.parametrize("defect", ["incomplete", "redacted", "limit"])
def test_current_scope_is_required_complete_unredacted_and_bounded(defect: str) -> None:
    release = _release()
    record = _resource()
    selected = (
        tuple(_resource(f"resource-{i}") for i in range(17)) if defect == "limit" else (record,)
    )
    scope = _scope(
        selected,
        release,
        complete=defect != "incomplete",
        redacted=defect == "redacted",
    )
    result = compare_resource_configuration(
        query_result=scope,
        before=project_configuration_snapshot(
            query_result=scope,
            view=_history((record,), release, as_of=BEFORE),
        ),
        after=project_configuration_snapshot(
            query_result=scope,
            view=_history((record,), release, as_of=NOW),
        ),
    )
    assert result["complete"] is False
    assert result["rows"] == []


async def test_function_accepts_scoped_snapshot_dependencies_and_rejects_time_drift() -> None:
    declaration = resource_configuration_function_type()
    release = build_ontology_release(function_types=(declaration,))
    record = _resource()
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(declaration, resource_configuration_changes_function(release))
    scope = _scope((record,), release)
    arguments = {
        "query_result": scope.model_dump(mode="json"),
        "before_snapshot": project_configuration_snapshot(
            query_result=scope,
            view=_history((record,), release, as_of=BEFORE),
        ).model_dump(mode="json"),
        "after_snapshot": project_configuration_snapshot(
            query_result=scope,
            view=_history((record,), release, as_of=NOW),
        ).model_dump(mode="json"),
        "before_as_of": BEFORE.isoformat(),
        "after_as_of": NOW.isoformat(),
        "known_at": NOW.isoformat(),
    }
    context = FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
        evidence_refs=(scope.receipt.projected_result_digest,),
    )
    result = await registry.invoke(RESOURCE_CONFIGURATION_FUNCTION_NAME, arguments, context=context)
    assert isinstance(result, dict) and result["complete"] is True
    arguments["before_as_of"] = (BEFORE - timedelta(minutes=1)).isoformat()
    with pytest.raises(ValueError, match="time boundary"):
        await registry.invoke(RESOURCE_CONFIGURATION_FUNCTION_NAME, arguments, context=context)


@pytest.mark.parametrize("defect", ["role", "purpose", "release", "cutoff"])
async def test_function_does_not_reuse_a_scope_from_another_context(defect: str) -> None:
    release = _release()
    record = _resource()
    scope_release = build_ontology_release() if defect == "release" else release
    scope = _scope((record,), scope_release)
    arguments = {
        "query_result": scope.model_dump(mode="json"),
        "before_snapshot": project_configuration_snapshot(
            query_result=scope,
            view=_history((record,), release, as_of=BEFORE),
        ).model_dump(mode="json"),
        "after_snapshot": project_configuration_snapshot(
            query_result=scope,
            view=_history((record,), release, as_of=NOW),
        ).model_dump(mode="json"),
        "before_as_of": BEFORE.isoformat(),
        "after_as_of": NOW.isoformat(),
        "known_at": (NOW + timedelta(seconds=6) if defect == "cutoff" else NOW).isoformat(),
    }
    context = FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role=CeilingRole.CONTRIBUTOR if defect == "role" else CeilingRole.READER,
        purposes=("incident-review",) if defect == "purpose" else ("operations-review",),
        evidence_refs=(scope.receipt.projected_result_digest,),
    )
    function = resource_configuration_changes_function(release)
    expected = ValueError if defect == "cutoff" else PermissionError
    with pytest.raises(expected):
        await function(arguments, context)
