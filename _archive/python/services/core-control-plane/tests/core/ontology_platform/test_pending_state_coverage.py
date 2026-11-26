"""Skew-bounded pending-state coverage: certification, refresh, receipt, and admission."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.models import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
)
from fdai.core.ontology_platform.pending_state_coverage import (
    COVERAGE_REF_PREFIX,
    PendingObservation,
    PendingStateCoverageLedger,
    PendingStateCoverageReceipt,
    PendingStateDescriptor,
    PendingStateDescriptorUnavailableError,
    PendingStateRefresher,
    PendingStateSources,
    bind_pending_state,
    certified_plan_digest,
    certify_pending_state_shape,
    coverage_admits,
    pending_state_plan_scope,
    resource_type_constraint,
)
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _apply_state_overlay,
    _projected_result_digest,
)
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_FUNCTION_NAME,
    resource_state_function_type,
    resource_state_inventory_function,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.exact_resource_state import (
    ExactResourceStateReading,
    ExactResourceStateUnavailableError,
)
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    canonical_json,
    content_digest,
)

NOW = datetime(2026, 8, 21, 11, 0, tzinfo=UTC)
GENERATION = "generation-a"
VM = "compute.vm"
ARM_PREFIX = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg"
REQUEST = ProjectionRequest(
    caller_role=CeilingRole.READER, declared_purposes=frozenset({"operations-review"})
)
_RELEASE = build_ontology_release(function_types=(resource_state_function_type(),))


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _definition(*predicates: ObjectPredicate) -> ObjectSetDefinition:
    return ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=predicates
        or (
            ObjectPredicate(property="type", equals=VM),
            ObjectPredicate(
                property="properties",
                operator=ObjectPredicateOperator.CONTAINS,
                equals=STATE_FACT_METADATA_PROPERTY,
            ),
        ),
        as_of=NOW,
        purpose="operations-review",
        limit=1000,
        include_relationships=False,
    )


def _vm(name: str, state: str, *, observed_at: datetime) -> OntologyObjectRecord:
    metadata = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision=GENERATION,
        effective_at=observed_at,
        recorded_at=observed_at,
        evidence_cutoff=observed_at,
        freshness_ceiling_seconds=3600,
        completeness=1.0,
        synthetic=False,
        evidence_refs=(f"inventory-generation:{GENERATION}",),
    ).to_mapping()
    return OntologyObjectRecord(
        id=f"scope-a/resource-group/rg/{name}",
        object_type="Resource",
        properties={
            "id": f"scope-a/resource-group/rg/{name}",
            "name": name,
            "type": VM,
            "properties": {"state": state, STATE_FACT_METADATA_PROPERTY: {"state": metadata}},
        },
    )


def _secured(
    objects: Sequence[OntologyObjectRecord],
    *,
    cutoff: datetime = NOW,
    pending: bool = True,
    definition: ObjectSetDefinition | None = None,
) -> SecuredObjectSetQueryResult:
    materialization = ObjectSetMaterialization(
        definition=definition or _definition(),
        graph=OntologyGraphSnapshot(
            objects=tuple(objects),
            links=(),
            source_complete=not pending,
            source_incomplete_reason="inventory_observation_pending" if pending else None,
            source_generation=GENERATION,
        ),
        concrete_types=("Resource",),
        truncated=False,
    )
    return SecuredObjectSetQueryResult(
        materialization=materialization,
        receipt=SecuredObjectSetQueryReceipt(
            ontology_release=_RELEASE.ref(),
            projected_result_digest=_projected_result_digest(materialization),
            purpose="operations-review",
            caller_role=CeilingRole.READER,
            observation_cutoff=cutoff,
            as_of_skew_seconds=5,
            returned_object_count=len(objects),
            returned_link_count=0,
            complete=not pending,
            truncated=False,
            source_complete=not pending,
            source_generation=GENERATION,
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


def _plan(
    definition: ObjectSetDefinition | None = None,
    *,
    function_name: str = RESOURCE_STATE_FUNCTION_NAME,
    extra_consumer: bool = False,
) -> OntologyQueryPlan:
    scope_definition = (definition or _definition()).model_dump(mode="json")
    nodes = [
        OntologyQueryNode(
            node_id="resource-state-scope",
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json({"definition": scope_definition}),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="resource-state-filter",
            kind=QueryNodeKind.FUNCTION,
            depends_on=("resource-state-scope",),
            arguments_json=canonical_json(
                {
                    "function_name": function_name,
                    "arguments": {"state_concepts": ["resource_state.running"]},
                    "dependency_arguments": {"resource-state-scope": "query_result"},
                }
            ),
            output_kind="query.table",
        ),
    ]
    if extra_consumer:
        nodes.append(
            OntologyQueryNode(
                node_id="resource-state-other",
                kind=QueryNodeKind.FUNCTION,
                depends_on=("resource-state-scope",),
                arguments_json=canonical_json({"function_name": "query.other"}),
                output_kind="query.table",
            )
        )
    header: dict[str, Any] = {
        "schema_version": "1.0.0",
        "ontology_release_digest": _digest("release"),
        "semantic_catalog_digest": _digest("catalog"),
        "problem_frame_digest": _digest("frame"),
        "purpose": "operations-review",
        "caller_role": "reader",
        "output_node_ids": ["resource-state-filter"],
    }
    digest = content_digest(
        {
            **header,
            "nodes": [node.model_dump(mode="json") for node in nodes],
            "output_node_ids": ("resource-state-filter",),
            "execution_authority": False,
        }
    )
    return OntologyQueryPlan(**header, nodes=tuple(nodes), plan_digest=digest)


def _observation(
    name: str, *, effective_at: datetime = NOW - timedelta(seconds=30), **changes: Any
) -> PendingObservation:
    values: dict[str, Any] = {
        "observation_id": f"observation-{name}",
        "subject_ref": f"scope-a/resource-group/rg/{name}",
        "subject_type": VM,
        "provider_ref": f"{ARM_PREFIX}/providers/Microsoft.Compute/virtualMachines/{name}",
        "mutation_kind": "upsert",
        "tombstone": False,
        "effective_at": effective_at,
    }
    values.update(changes)
    return PendingObservation(**values)


class _Clock:
    def __init__(self, start: datetime = NOW) -> None:
        self.value = start

    def __call__(self) -> datetime:
        return self.value


class _Gateway:
    def __init__(self, base: Sequence[OntologyObjectRecord], clock: _Clock) -> None:
        self._base = tuple(base)
        self._clock = clock
        self.overlays: list[Mapping[str, Mapping[str, Any]] | None] = []
        self.objects_override: tuple[OntologyObjectRecord, ...] | None = None

    async def materialize(
        self,
        definition: ObjectSetDefinition,
        *,
        projection_request: ProjectionRequest,
        state_overlay: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> SecuredObjectSetQueryResult:
        self.overlays.append(state_overlay)
        self._clock.value += timedelta(milliseconds=200)
        objects = self.objects_override or self._base
        unprojected = _secured(objects, cutoff=self._clock(), definition=definition)
        if state_overlay is None:
            return unprojected
        materialization = _apply_state_overlay(unprojected.materialization, state_overlay)
        return _secured(materialization.graph.objects, cutoff=self._clock(), definition=definition)


class _Descriptors:
    def __init__(self, *descriptors: PendingStateDescriptor) -> None:
        self._descriptors = list(descriptors)
        self.calls: list[tuple[tuple[str, ...], int]] = []

    async def pending_state_descriptor(
        self, *, subject_types: Sequence[str], limit: int
    ) -> PendingStateDescriptor:
        self.calls.append((tuple(subject_types), limit))
        if len(self._descriptors) > 1:
            return self._descriptors.pop(0)
        return self._descriptors[0]


class _FailingDescriptors:
    async def pending_state_descriptor(
        self, *, subject_types: Sequence[str], limit: int
    ) -> PendingStateDescriptor:
        raise PendingStateDescriptorUnavailableError("database unavailable")


class _StateReader:
    def __init__(
        self,
        states: Mapping[str, str],
        *,
        provider_time: datetime = NOW - timedelta(seconds=1),
        error: Exception | None = None,
    ) -> None:
        self._states = states
        self._provider_time = provider_time
        self._error = error
        self.timeouts: list[float] = []

    def supports(self, resource_type: str) -> bool:
        return resource_type == VM

    async def read_state(
        self,
        *,
        resource_ref: str,
        resource_type: str,
        provider_ref: str,
        timeout_seconds: float,
    ) -> ExactResourceStateReading | None:
        self.timeouts.append(timeout_seconds)
        if self._error is not None:
            raise self._error
        state = self._states.get(resource_ref)
        if state is None:
            return None
        return ExactResourceStateReading(
            resource_ref=resource_ref,
            resource_type=resource_type,
            state=state,
            provider_time=self._provider_time,
            evidence_ref=_digest(f"arm:{resource_ref}:{state}").replace(
                "sha256:", "arm-state:sha256:"
            ),
        )


class _Store:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}

    async def write_state(self, key: str, value: Mapping[str, Any]) -> None:
        self.values[key] = dict(value)

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        return self.values.get(key)


def _descriptor(
    *observations: PendingObservation, overflow: bool = False
) -> PendingStateDescriptor:
    return PendingStateDescriptor(
        generation=GENERATION, observations=tuple(observations), overflow=overflow
    )


def _refresher(
    gateway: _Gateway,
    descriptors: Any,
    reader: _StateReader,
    clock: _Clock,
    store: _Store | None = None,
) -> tuple[PendingStateRefresher, PendingStateCoverageLedger]:
    ledger = PendingStateCoverageLedger(store=store or _Store())
    return (
        PendingStateRefresher(
            gateway=gateway,
            descriptor_reader=descriptors,
            state_reader=reader,
            ledger=ledger,
            clock=clock,
        ),
        ledger,
    )


async def _invoke_state_function(
    secured: SecuredObjectSetQueryResult, coverage: Mapping[str, Any] | None
) -> dict[str, Any]:
    declaration = resource_state_function_type()
    registry = OntologyFunctionRegistry(release=_RELEASE)
    registry.register_contextual(declaration, resource_state_inventory_function(_RELEASE))
    result = await registry.invoke(
        RESOURCE_STATE_FUNCTION_NAME,
        {
            "query_result": secured.model_dump(mode="json"),
            "state_concepts": ["resource_state.running"],
            **({"pending_state_coverage": dict(coverage)} if coverage is not None else {}),
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    assert isinstance(result, dict)
    return result


# --- Certification -------------------------------------------------------------------------


def test_type_constraint_reads_exact_equals_and_in_predicates() -> None:
    assert resource_type_constraint((ObjectPredicate(property="type", equals=VM),)) == (VM,)
    assert resource_type_constraint(
        (
            ObjectPredicate(
                property="type", operator=ObjectPredicateOperator.IN, values=("b", "a", "a")
            ),
        )
    ) == ("a", "b")
    assert resource_type_constraint((ObjectPredicate(property="name", equals="vm-a"),)) == ()


def test_only_a_terminal_state_filter_over_a_typed_resource_set_is_certified() -> None:
    assert certify_pending_state_shape(_plan()) == frozenset({"resource-state-scope"})
    assert certify_pending_state_shape(_plan(function_name="query.other")) == frozenset()
    assert certify_pending_state_shape(_plan(extra_consumer=True)) == frozenset()
    untyped = _definition(ObjectPredicate(property="name", equals="vm-a"))
    assert certify_pending_state_shape(_plan(untyped)) == frozenset()


def test_a_predicate_on_overlaid_provider_properties_is_never_certified() -> None:
    filtered = _definition(
        ObjectPredicate(property="type", equals=VM),
        ObjectPredicate(property="properties", operator=ObjectPredicateOperator.EXISTS),
    )
    assert certify_pending_state_shape(_plan(filtered)) == frozenset()
    stable = _definition(
        ObjectPredicate(property="type", equals=VM),
        ObjectPredicate(
            property="type", operator=ObjectPredicateOperator.NOT_EQUALS, equals="other"
        ),
        ObjectPredicate(property="location", equals="region-a"),
    )
    assert certify_pending_state_shape(_plan(stable)) == frozenset({"resource-state-scope"})


def test_the_plan_scope_exposes_the_digest_only_to_certified_nodes() -> None:
    plan = _plan()
    assert certified_plan_digest("resource-state-scope") is None
    with pending_state_plan_scope(plan):
        digest = certified_plan_digest("resource-state-scope")
        assert digest is not None and digest.startswith("sha256:")
        assert certified_plan_digest("resource-state-filter") is None
    assert certified_plan_digest("resource-state-scope") is None


# --- Gateway overlay -----------------------------------------------------------------------


def test_the_overlay_replaces_only_named_provider_properties() -> None:
    first = _vm("vm-a", "deallocated", observed_at=NOW - timedelta(minutes=5))
    second = _vm("vm-b", "running", observed_at=NOW - timedelta(minutes=5))
    materialization = _secured((first, second)).materialization
    updated = _apply_state_overlay(materialization, {first.id: {"state": "running"}})
    by_id = {item.id: item for item in updated.graph.objects}
    assert by_id[first.id].properties["properties"] == {"state": "running"}
    assert by_id[second.id].properties == second.properties
    with pytest.raises(ValueError, match="outside the object set"):
        _apply_state_overlay(materialization, {"scope-a/other": {"state": "running"}})


# --- Refresher -----------------------------------------------------------------------------


async def _covered_run() -> tuple[
    SecuredObjectSetQueryResult,
    SecuredObjectSetQueryResult,
    tuple[str, ...],
    PendingStateCoverageLedger,
    _Store,
]:
    clock = _Clock()
    records = (
        _vm("vm-a", "deallocated", observed_at=NOW - timedelta(minutes=5)),
        _vm("vm-b", "running", observed_at=NOW - timedelta(minutes=5)),
    )
    gateway = _Gateway(records, clock)
    first = _secured(records)
    descriptors = _Descriptors(_descriptor(_observation("vm-a")))
    reader = _StateReader({records[0].id: "running"})
    store = _Store()
    refresher, ledger = _refresher(gateway, descriptors, reader, clock, store)
    with pending_state_plan_scope(_plan()):
        second, refs = await refresher.cover(
            node_id="resource-state-scope",
            definition=_definition(),
            projection_request=REQUEST,
            secured=first,
        )
    return first, second, refs, ledger, store


async def test_a_covered_refresh_records_a_durable_receipt_the_state_function_admits() -> None:
    first, second, refs, ledger, store = await _covered_run()

    assert second is not first
    assert refs[0].startswith(COVERAGE_REF_PREFIX)
    assert refs[1].startswith("arm-state:sha256:")
    assert second.receipt.observation_cutoff > first.receipt.observation_cutoff
    # The graph keeps its typed gap; only the composite receipt can admit completeness.
    assert second.materialization.graph.source_complete is False
    assert len(store.values) == 1
    receipt = await ledger.resolve(refs)
    assert receipt is not None
    assert receipt.facts[0].state == "running"
    assert coverage_admits(receipt.model_dump(mode="json"), second)

    without = await _invoke_state_function(second, None)
    assert without["complete"] is False
    covered = await _invoke_state_function(second, receipt.model_dump(mode="json"))
    assert covered["complete"] is True
    assert {row["values"]["name"] for row in covered["rows"]} == {"vm-a", "vm-b"}


async def test_a_receipt_never_admits_a_different_result() -> None:
    first, second, refs, ledger, _ = await _covered_run()
    receipt = await ledger.resolve(refs)
    assert receipt is not None
    coverage = receipt.model_dump(mode="json")
    assert not coverage_admits(coverage, first)
    assert not coverage_admits({"decision": "covered"}, second)
    assert not coverage_admits(None, second)


async def test_the_ledger_resolves_from_the_store_and_rejects_a_tampered_receipt() -> None:
    _, _, refs, _, store = await _covered_run()
    fresh = PendingStateCoverageLedger(store=store)
    assert await fresh.resolve(refs) is not None
    (key,) = store.values
    store.values[key] = {**store.values[key], "node_id": "another-node"}
    assert await PendingStateCoverageLedger(store=store).resolve(refs) is None
    assert await fresh.resolve(("ontology-object-set:sha256:" + "0" * 64,)) is None
    receipt = PendingStateCoverageReceipt.model_validate(store.values[key])
    assert await fresh.coverage_argument("query.other", refs) is None
    assert receipt.node_id == "another-node"


@pytest.mark.parametrize(
    ("descriptor", "states", "provider_time", "reason"),
    [
        (_descriptor(_observation("vm-a"), overflow=True), {"vm-a": "running"}, None, "overflow"),
        (_descriptor(_observation("vm-a", tombstone=True)), {"vm-a": "running"}, None, "tomb"),
        (
            _descriptor(_observation("vm-a", mutation_kind="delete")),
            {"vm-a": "running"},
            None,
            "delete",
        ),
        (_descriptor(_observation("vm-a", provider_ref=None)), {"vm-a": "running"}, None, "ref"),
        (_descriptor(_observation("vm-z")), {"vm-z": "running"}, None, "absent"),
        (_descriptor(_observation("vm-a", subject_type="other")), {"vm-a": "x"}, None, "type"),
        (_descriptor(), {}, None, "empty"),
        (_descriptor(_observation("vm-a")), {}, None, "no-reading"),
        (
            _descriptor(_observation("vm-a")),
            {"vm-a": "running"},
            NOW - timedelta(minutes=2),
            "stale",
        ),
    ],
)
async def test_every_unprovable_case_keeps_the_partial_result(
    descriptor: PendingStateDescriptor,
    states: Mapping[str, str],
    provider_time: datetime | None,
    reason: str,
) -> None:
    clock = _Clock()
    records = (_vm("vm-a", "deallocated", observed_at=NOW - timedelta(minutes=5)),)
    gateway = _Gateway(records, clock)
    first = _secured(records)
    reader = _StateReader(
        {f"scope-a/resource-group/rg/{name}": state for name, state in states.items()},
        provider_time=provider_time or NOW - timedelta(seconds=1),
    )
    refresher, _ = _refresher(gateway, _Descriptors(descriptor), reader, clock)
    with pending_state_plan_scope(_plan()):
        result, refs = await refresher.cover(
            node_id="resource-state-scope",
            definition=_definition(),
            projection_request=REQUEST,
            secured=first,
        )
    assert (result, refs) == (first, ()), reason


async def test_an_uncertified_node_or_complete_result_is_never_refreshed() -> None:
    clock = _Clock()
    records = (_vm("vm-a", "deallocated", observed_at=NOW - timedelta(minutes=5)),)
    descriptors = _Descriptors(_descriptor(_observation("vm-a")))
    refresher, _ = _refresher(
        _Gateway(records, clock), descriptors, _StateReader({records[0].id: "running"}), clock
    )
    uncertified = _secured(records)
    assert await refresher.cover(
        node_id="resource-state-scope",
        definition=_definition(),
        projection_request=REQUEST,
        secured=uncertified,
    ) == (uncertified, ())
    complete = _secured(records, pending=False)
    with pending_state_plan_scope(_plan()):
        assert await refresher.cover(
            node_id="resource-state-scope",
            definition=_definition(),
            projection_request=REQUEST,
            secured=complete,
        ) == (complete, ())
    assert descriptors.calls == []


async def test_an_exhausted_skew_budget_skips_every_provider_read() -> None:
    clock = _Clock(NOW + timedelta(seconds=3))
    records = (_vm("vm-a", "deallocated", observed_at=NOW - timedelta(minutes=5)),)
    reader = _StateReader({records[0].id: "running"})
    refresher, _ = _refresher(
        _Gateway(records, clock),
        _Descriptors(_descriptor(_observation("vm-a"))),
        reader,
        clock,
    )
    first = _secured(records)
    with pending_state_plan_scope(_plan()):
        assert await refresher.cover(
            node_id="resource-state-scope",
            definition=_definition(),
            projection_request=REQUEST,
            secured=first,
        ) == (first, ())
    assert reader.timeouts == []


@pytest.mark.parametrize(
    "error",
    [ExactResourceStateUnavailableError("throttled"), TimeoutError()],
)
async def test_an_unavailable_provider_keeps_the_partial_result(error: Exception) -> None:
    clock = _Clock()
    records = (_vm("vm-a", "deallocated", observed_at=NOW - timedelta(minutes=5)),)
    refresher, _ = _refresher(
        _Gateway(records, clock),
        _Descriptors(_descriptor(_observation("vm-a"))),
        _StateReader({}, error=error),
        clock,
    )
    first = _secured(records)
    with pending_state_plan_scope(_plan()):
        assert await refresher.cover(
            node_id="resource-state-scope",
            definition=_definition(),
            projection_request=REQUEST,
            secured=first,
        ) == (first, ())


async def test_an_unavailable_descriptor_keeps_the_partial_result() -> None:
    clock = _Clock()
    records = (_vm("vm-a", "deallocated", observed_at=NOW - timedelta(minutes=5)),)
    refresher, _ = _refresher(
        _Gateway(records, clock), _FailingDescriptors(), _StateReader({}), clock
    )
    first = _secured(records)
    with pending_state_plan_scope(_plan()):
        assert await refresher.cover(
            node_id="resource-state-scope",
            definition=_definition(),
            projection_request=REQUEST,
            secured=first,
        ) == (first, ())


async def test_a_descriptor_change_between_passes_fails_the_fence() -> None:
    clock = _Clock()
    records = (_vm("vm-a", "deallocated", observed_at=NOW - timedelta(minutes=5)),)
    changed = _descriptor(_observation("vm-a"), _observation("vm-a", observation_id="later"))
    store = _Store()
    refresher, _ = _refresher(
        _Gateway(records, clock),
        _Descriptors(_descriptor(_observation("vm-a")), changed),
        _StateReader({records[0].id: "running"}),
        clock,
        store,
    )
    first = _secured(records)
    with pending_state_plan_scope(_plan()):
        assert await refresher.cover(
            node_id="resource-state-scope",
            definition=_definition(),
            projection_request=REQUEST,
            secured=first,
        ) == (first, ())
    assert store.values == {}


async def test_a_changed_member_set_between_passes_fails_the_fence() -> None:
    clock = _Clock()
    records = (_vm("vm-a", "deallocated", observed_at=NOW - timedelta(minutes=5)),)
    gateway = _Gateway(records, clock)
    gateway.objects_override = (
        *records,
        _vm("vm-new", "running", observed_at=NOW - timedelta(minutes=5)),
    )
    refresher, _ = _refresher(
        gateway,
        _Descriptors(_descriptor(_observation("vm-a"))),
        _StateReader({records[0].id: "running"}),
        clock,
    )
    first = _secured(records)
    with pending_state_plan_scope(_plan()):
        assert await refresher.cover(
            node_id="resource-state-scope",
            definition=_definition(),
            projection_request=REQUEST,
            secured=first,
        ) == (first, ())


def test_binding_requires_both_sources_and_a_durable_store() -> None:
    clock = _Clock()
    sources = PendingStateSources(
        descriptor_reader=_Descriptors(_descriptor()), state_reader=_StateReader({})
    )
    gateway = _Gateway((), clock)
    assert bind_pending_state(None, gateway=gateway, store=_Store(), clock=clock) == (None, None)
    assert bind_pending_state(sources, gateway=gateway, store=None, clock=clock) == (None, None)
    refresher, ledger = bind_pending_state(sources, gateway=gateway, store=_Store(), clock=clock)
    assert isinstance(refresher, PendingStateRefresher)
    assert isinstance(ledger, PendingStateCoverageLedger)
