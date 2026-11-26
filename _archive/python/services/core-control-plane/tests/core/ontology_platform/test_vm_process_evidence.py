"""VM process CPU evidence contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
    ObjectSetTruncationReason,
)
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.core.ontology_platform.vm_process_evidence import (
    VM_PROCESS_CPU_FUNCTION_NAME,
    VmProcessCpuCollection,
    VmProcessCpuObservation,
    vm_process_cpu_function,
    vm_process_cpu_function_type,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord

NOW = datetime(2026, 8, 26, 5, 0, tzinfo=UTC)
START = NOW - timedelta(minutes=10)


def _query_result(*, complete: bool = True) -> SecuredObjectSetQueryResult:
    declaration = vm_process_cpu_function_type()
    release = build_ontology_release(function_types=(declaration,))
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=2,
    )
    reason = None if complete else ObjectSetTruncationReason.RESULT_LIMIT
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(
            objects=(
                OntologyObjectRecord(
                    id="resource-vm-example",
                    object_type="Resource",
                    properties={"name": "vm-example", "type": "compute.vm"},
                ),
            ),
            links=(),
            truncated=not complete,
        ),
        concrete_types=("Resource",),
        truncated=not complete,
        truncation_reason=reason,
    )
    return SecuredObjectSetQueryResult(
        materialization=materialization,
        receipt=SecuredObjectSetQueryReceipt(
            ontology_release=release.ref(),
            projected_result_digest=_projected_result_digest(materialization),
            purpose="operations-review",
            caller_role="reader",
            observation_cutoff=NOW,
            as_of_skew_seconds=0,
            returned_object_count=1,
            returned_link_count=0,
            complete=complete,
            truncated=not complete,
            truncation_reason=reason,
            redactions=ObjectSetRedactionSummary(
                objects_with_redactions=0,
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


def _observation(
    process_name: str = "worker-example",
    *,
    resource_id: str = "resource-vm-example",
    average: float = 72.0,
    maximum: float = 91.0,
) -> VmProcessCpuObservation:
    return VmProcessCpuObservation(
        resource_id=resource_id,
        process_name=process_name,
        average_cpu_percent=average,
        maximum_cpu_percent=maximum,
        sample_count=10,
        first_observed_at=START,
        last_observed_at=NOW,
        evidence_ref=f"azure-monitor-perf:{process_name}",
    )


def _collection(
    observations: tuple[VmProcessCpuObservation, ...],
    *,
    complete: bool = True,
    truncated: bool = False,
    limitation: str | None = None,
) -> VmProcessCpuCollection:
    return VmProcessCpuCollection(
        resource_id="resource-vm-example",
        start=START,
        end=NOW,
        observed_at=NOW,
        observations=observations,
        complete=complete,
        truncated=truncated,
        limitation=limitation,
        attempt_ref="azure-monitor-perf:attempt",
    )


class _Reader:
    def __init__(self, collection: VmProcessCpuCollection) -> None:
        self.collection = collection
        self.calls: list[tuple[str, datetime, datetime, int]] = []

    async def read_process_cpu(
        self,
        *,
        resource_id: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> VmProcessCpuCollection:
        self.calls.append((resource_id, start, end, limit))
        return self.collection


async def _invoke(
    reader: _Reader,
    *,
    complete_scope: bool = True,
    start: datetime = START,
    end: datetime = NOW,
) -> dict[str, object]:
    declaration = vm_process_cpu_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        vm_process_cpu_function(release, reader=reader),
    )
    result = await registry.invoke(
        VM_PROCESS_CPU_FUNCTION_NAME,
        {
            "query_result": _query_result(complete=complete_scope).model_dump(mode="json"),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 8,
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    assert isinstance(result, dict)
    return result


def test_collection_preserves_ordered_exact_process_evidence() -> None:
    collection = _collection(
        (
            _observation(),
            _observation("sidecar-example", average=20.0, maximum=35.0),
        )
    )

    assert tuple(item.process_name for item in collection.observations) == (
        "worker-example",
        "sidecar-example",
    )
    assert collection.complete is True
    assert collection.truncated is False


@pytest.mark.parametrize(
    "observations",
    (
        (_observation(resource_id="resource-other"),),
        (_observation(), _observation("WORKER-EXAMPLE")),
        (_observation("low", average=10.0), _observation("high", average=80.0)),
    ),
)
def test_collection_rejects_scope_identity_or_ordering_conflicts(
    observations: tuple[VmProcessCpuObservation, ...],
) -> None:
    with pytest.raises(ValueError):
        _collection(observations)


@pytest.mark.parametrize(
    ("average", "maximum"),
    ((-1.0, 1.0), (float("nan"), 1.0), (4.0, 3.0)),
)
def test_observation_rejects_invalid_cpu_values(average: float, maximum: float) -> None:
    with pytest.raises(ValueError):
        _observation(average=average, maximum=maximum)


def test_collection_rejects_false_complete_truncation() -> None:
    with pytest.raises(ValueError, match="completeness"):
        _collection((_observation(),), truncated=True)


def test_collection_accepts_explicit_unavailable_evidence() -> None:
    collection = _collection(
        (),
        complete=False,
        limitation="provider_unavailable",
    )

    assert collection.observations == ()
    assert collection.complete is False


def test_collection_rejects_empty_complete_evidence() -> None:
    with pytest.raises(ValueError, match="at least one observation"):
        _collection(())


def test_function_declares_dependency_only_no_authority_read() -> None:
    declaration = vm_process_cpu_function_type()

    assert declaration.name == VM_PROCESS_CPU_FUNCTION_NAME
    assert declaration.input_schema["properties"]["query_result"] == {
        "type": "object",
        "x-fdai-dependency-only": True,
    }
    assert declaration.required_role is CeilingRole.READER
    assert declaration.network_allowed is False
    assert declaration.credentials_allowed is False


async def test_function_projects_exact_process_rows() -> None:
    reader = _Reader(_collection((_observation(),)))

    result = await _invoke(reader)

    assert reader.calls == [("resource-vm-example", START, NOW, 8)]
    assert result["complete"] is True
    assert result["truncation_reason"] is None
    row = result["rows"][0]["values"]
    assert row["process_name"] == "worker-example"
    assert row["average_cpu_percent"] == 72.0
    assert row["evidence_ref"] == "azure-monitor-perf:worker-example"
    assert row["collection_observed_at"] == NOW.isoformat()
    assert row["attempt_ref"] == "azure-monitor-perf:attempt"
    assert row["execution_authority"] is False


async def test_function_stops_before_reader_on_incomplete_scope() -> None:
    reader = _Reader(_collection((_observation(),)))

    result = await _invoke(reader, complete_scope=False)

    assert reader.calls == []
    assert result["complete"] is False
    assert result["truncation_reason"] == "resource_scope_incomplete"


async def test_function_rejects_unbounded_or_future_windows_before_reader() -> None:
    reader = _Reader(_collection((_observation(),)))

    with pytest.raises(ValueError, match="one hour"):
        await _invoke(reader, start=NOW - timedelta(hours=2))
    with pytest.raises(ValueError, match="observation cutoff"):
        await _invoke(reader, end=NOW + timedelta(minutes=1))

    assert reader.calls == []
