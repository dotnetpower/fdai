"""Scoped history source privacy, admission, and intermediate query-result regressions."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import pytest
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.query_execution import QueryNodeResult
from fdai.core.ontology_platform.query_receipt_authority import SecuredQueryReceiptAuthority
from fdai.core.ontology_platform.query_source_handlers import FunctionNodeHandler
from fdai.core.ontology_platform.query_values import QueryTable
from fdai.core.ontology_platform.resource_configuration_queries import (
    RESOURCE_CONFIGURATION_FUNCTION_NAME,
    compare_resource_configuration,
    resource_configuration_changes_function,
    resource_configuration_function_type,
)
from fdai.core.ontology_platform.resource_configuration_snapshots import (
    RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME,
    ScopedConfigurationRecord,
    ScopedConfigurationSnapshot,
    project_configuration_snapshot,
    resource_configuration_snapshot_function,
    resource_configuration_snapshot_function_type,
)
from fdai.core.ontology_platform.topology_history import TopologyRevisionBatch
from fdai.shared.contracts.models import CeilingRole, OntologyRelease
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.ontology_query import (
    EvidenceAuthority,
    OntologyQueryNode,
    QueryNodeKind,
    canonical_json,
    content_digest,
)
from tests.core.ontology_platform.test_resource_configuration_queries import (
    BEFORE,
    NOW,
    _batch,
    _history,
    _resource,
    _scope,
)


class _Reader:
    def __init__(self, *batches: TopologyRevisionBatch, failure: bool = False) -> None:
        self.batches = batches
        self.failure = failure
        self.calls: list[tuple[datetime, datetime]] = []

    async def read(
        self, *, as_of: datetime, known_at: datetime
    ) -> tuple[TopologyRevisionBatch, ...]:
        self.calls.append((as_of, known_at))
        if self.failure:
            raise OSError("unreviewed source details")
        return self.batches


def _release() -> OntologyRelease:
    return build_ontology_release(
        function_types=(
            resource_configuration_function_type(),
            resource_configuration_snapshot_function_type(),
        ),
    )


def _context(digest: str) -> FunctionInvocationContext:
    return FunctionInvocationContext(
        caller_agent="Bragi",
        caller_role=CeilingRole.READER,
        purposes=("operations-review",),
        evidence_refs=(digest,),
    )


async def test_scoped_source_never_returns_unselected_facts_payloads_or_global_refs() -> None:
    release = _release()
    selected = _resource(updates={"secret": "unreviewed-selected-payload"})
    hidden = _resource("unselected-resource", updates={"model_name": "unselected-model"})
    scope = _scope((selected,), release)
    reader = _Reader(_batch((selected, hidden), release, as_of=BEFORE))
    source = resource_configuration_snapshot_function(release, reader=reader)
    result = await source(
        {"query_result": scope, "as_of": BEFORE.isoformat(), "known_at": NOW.isoformat()},
        _context(scope.receipt.projected_result_digest),
    )
    assert isinstance(result, ScopedConfigurationSnapshot)
    assert result.complete and len(result.records) == 1
    assert result.records[0].projection.values["capacity_tpm"] == 6000
    serialized = result.model_dump_json()
    for absent in (
        "unselected-resource",
        "unselected-model",
        "unreviewed-selected-payload",
        "example-generation",
        "inventory:",
        "revision-before",
        "source_receipt_digests",
    ):
        assert absent not in serialized
    assert reader.calls == [(BEFORE, NOW)]
    assert result.execution_authority is False


@pytest.mark.parametrize("defect", ["unissued", "role", "purpose", "release", "cutoff"])
async def test_source_checks_admission_before_reader_io(defect: str) -> None:
    release = _release()
    scope = _scope((_resource(),), build_ontology_release() if defect == "release" else release)
    context = _context(scope.receipt.projected_result_digest)
    if defect == "unissued":
        context = context.model_copy(update={"evidence_refs": ()})
    if defect == "role":
        context = context.model_copy(update={"caller_role": CeilingRole.CONTRIBUTOR})
    if defect == "purpose":
        context = context.model_copy(update={"purposes": ("incident-review",)})
    reader = _Reader()
    source = resource_configuration_snapshot_function(release, reader=reader)
    known = NOW + timedelta(seconds=6) if defect == "cutoff" else NOW
    with pytest.raises(ValueError if defect == "cutoff" else PermissionError):
        await source(
            {"query_result": scope, "as_of": BEFORE.isoformat(), "known_at": known.isoformat()},
            context,
        )
    assert not reader.calls


@pytest.mark.parametrize("defect", ["redacted", "incomplete", "limit", "empty"])
async def test_partial_or_redacted_scope_returns_unknown_without_history_read(defect: str) -> None:
    release = _release()
    resources = (
        tuple(_resource(f"resource-{i}") for i in range(17))
        if defect == "limit"
        else (() if defect == "empty" else (_resource(),))
    )
    scope = _scope(
        resources,
        release,
        complete=defect != "incomplete",
        redacted=defect == "redacted",
    )
    reader = _Reader()
    result = await resource_configuration_snapshot_function(release, reader=reader)(
        {"query_result": scope, "as_of": BEFORE.isoformat(), "known_at": NOW.isoformat()},
        _context(scope.receipt.projected_result_digest),
    )
    assert isinstance(result, ScopedConfigurationSnapshot)
    assert not result.complete and not result.records
    assert result.provenance_digest is None and not reader.calls


@pytest.mark.parametrize("failure", [False, True])
async def test_missing_baseline_or_unavailable_reader_returns_unknown(failure: bool) -> None:
    release = _release()
    scope = _scope((_resource(),), release)
    result = await resource_configuration_snapshot_function(
        release, reader=_Reader(failure=failure)
    )(
        {"query_result": scope, "as_of": BEFORE.isoformat(), "known_at": NOW.isoformat()},
        _context(scope.receipt.projected_result_digest),
    )
    assert isinstance(result, ScopedConfigurationSnapshot)
    assert not result.complete and not result.records
    assert "unreviewed source details" not in result.model_dump_json()


@pytest.mark.parametrize(
    "as_of",
    ["2026-09-06T11:00:00", "2026-09-07T11:00:00Z", "2026-08-01T11:00:00Z"],
)
async def test_source_time_boundary_is_aware_past_and_bounded(as_of: str) -> None:
    release = _release()
    scope = _scope((_resource(),), release)
    reader = _Reader()
    with pytest.raises(ValueError):
        await resource_configuration_snapshot_function(release, reader=reader)(
            {"query_result": scope, "as_of": as_of, "known_at": NOW.isoformat()},
            _context(scope.receipt.projected_result_digest),
        )
    assert not reader.calls


def test_snapshot_dto_cannot_carry_unreviewed_values_even_with_recomputed_digest() -> None:
    release = _release()
    resource = _resource()
    scope = _scope((resource,), release)
    snapshot = project_configuration_snapshot(
        query_result=scope,
        view=_history((resource,), release, as_of=BEFORE),
    )
    record = snapshot.records[0]
    values = {**record.projection.values, "provider_payload": "unreviewed-payload"}
    with pytest.raises(ValueError, match="unreviewed"):
        ScopedConfigurationRecord(
            resource_id=record.resource_id,
            resource_type=record.resource_type,
            values_json=canonical_json(values),
            projection_digest=content_digest(values),
        )


def test_comparison_rejects_a_snapshot_from_another_current_selection() -> None:
    release = _release()
    target = _resource()
    other = _resource("other-selected-resource")
    scope = _scope((target,), release)
    other_scope = _scope((other,), release)
    before = project_configuration_snapshot(
        query_result=other_scope,
        view=_history((other,), release, as_of=BEFORE),
    )
    after = project_configuration_snapshot(
        query_result=scope,
        view=_history((target,), release, as_of=NOW),
    )
    with pytest.raises(PermissionError, match="issued scope"):
        compare_resource_configuration(query_result=scope, before=before, after=after)


def test_generic_snapshot_dto_refuses_raw_reviewed_values() -> None:
    values = {"location": None, "sku_name": "raw-sku-value", "capacity_units": None}
    with pytest.raises(ValueError, match="field digests"):
        ScopedConfigurationRecord(
            resource_id="resource-example",
            resource_type="compute.vm",
            values_json=canonical_json(values),
            projection_digest=content_digest(values),
        )


def test_snapshot_cannot_be_reused_for_another_principal_with_identical_objects() -> None:
    release = _release()
    target = _resource()
    scope = _scope((target,), release)
    other_scope = scope.model_copy(
        update={
            "receipt": scope.receipt.model_copy(
                update={"principal_scope_digest": "sha256:" + "c" * 64}
            ),
        }
    )
    before = project_configuration_snapshot(
        query_result=scope,
        view=_history((target,), release, as_of=BEFORE),
    )
    after = project_configuration_snapshot(
        query_result=other_scope,
        view=_history((target,), release, as_of=NOW),
    )
    with pytest.raises(PermissionError, match="issued scope"):
        compare_resource_configuration(query_result=other_scope, before=before, after=after)


@pytest.mark.parametrize("issued", [True, False])
async def test_all_function_node_results_and_lineage_are_scoped_before_comparison(
    issued: bool,
) -> None:
    release = _release()
    before = _resource(updates={"secret": "unreviewed-before-payload"})
    after = _resource(updates={"capacity_units": 20, "capacity_transitioning": True})
    hidden = _resource("unselected-resource", updates={"model_name": "unselected-model"})
    scope = _scope((after,), release)
    reader = _Reader(
        _batch((before, hidden), release, as_of=BEFORE),
        _batch((after, hidden), release, as_of=NOW),
    )
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        resource_configuration_snapshot_function_type(),
        resource_configuration_snapshot_function(release, reader=reader),
    )
    registry.register_contextual(
        resource_configuration_function_type(),
        resource_configuration_changes_function(release),
    )
    authority = SecuredQueryReceiptAuthority(now=lambda: NOW)
    if issued:
        authority.issue(scope)
    handler = FunctionNodeHandler(
        registry,
        context=_context(scope.receipt.projected_result_digest),
        receipt_authority=authority,
        allow_presentation_read_dependencies=True,
    )
    dependencies = {
        "scope": QueryNodeResult(
            value=QueryTable(rows=(), complete=True),
            evidence_refs=(f"ontology-object-set-output:{scope.receipt.projected_result_digest}",),
            authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        ),
    }
    for node_id, as_of in (("before", BEFORE), ("after", NOW)):
        node = OntologyQueryNode(
            node_id=node_id,
            kind=QueryNodeKind.FUNCTION,
            depends_on=("scope",),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME,
                    "arguments": {"as_of": as_of.isoformat(), "known_at": NOW.isoformat()},
                    "dependency_arguments": {"scope": "query_result"},
                }
            ),
            output_kind="resource.configuration_snapshot",
        )
        if not issued:
            with pytest.raises(PermissionError, match="issued ObjectSet"):
                await handler(node, {"scope": dependencies["scope"]})
            assert not reader.calls
            return
        result = await handler(node, {"scope": dependencies["scope"]})
        assert isinstance(result.value, ScopedConfigurationSnapshot)
        payload = result.value.model_dump_json() + json.dumps(result.evidence_refs)
        assert "unselected-" not in payload and "unreviewed-before-payload" not in payload
        assert "inventory:" not in payload and "example-generation" not in payload
        dependencies[node_id] = result
    comparison = OntologyQueryNode(
        node_id="compare",
        kind=QueryNodeKind.FUNCTION,
        depends_on=("scope", "before", "after"),
        arguments_json=canonical_json(
            {
                "function_name": RESOURCE_CONFIGURATION_FUNCTION_NAME,
                "arguments": {
                    "before_as_of": BEFORE.isoformat(),
                    "after_as_of": NOW.isoformat(),
                    "known_at": NOW.isoformat(),
                },
                "dependency_arguments": {
                    "scope": "query_result",
                    "before": "before_snapshot",
                    "after": "after_snapshot",
                },
            }
        ),
        output_kind="query.table",
    )
    result = await handler(comparison, dependencies)
    assert isinstance(result.value, QueryTable)
    assert result.value.complete
    values: dict[str, Any] = result.value.rows[0].values
    assert values["before"]["capacity_units"] == 100
    assert values["after"]["capacity_units"] == 20
    assert "unselected-" not in result.value.canonical_json() + json.dumps(result.evidence_refs)
