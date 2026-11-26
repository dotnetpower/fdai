"""Cover pending same-type Resource updates with authoritative live state, within the skew budget.

A typed current-state read is partial while a same-type change waits for reconciliation. When the
verified plan is exactly ``ObjectSet -> query.resource_state_inventory``, the ObjectSet handler may
read each pending subject's state from its authoritative provider and materialize again with those
facts applied before security projection. The second materialization's cutoff follows every
reading, so no reading postdates the cutoff it supports. A durable composite receipt binds the
inputs and result; the state function reports completeness only when it resolves that receipt.
The graph itself is never changed, and its source completeness stays false.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import OrderedDict
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Protocol

from fdai_service_contracts.ontology_query import OntologyQueryPlan, QueryNodeKind
from pydantic import Field

from fdai.shared.contracts.models import ContractBase
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.exact_resource_state import (
    ExactResourceStateReader,
    ExactResourceStateReading,
    ExactResourceStateUnavailableError,
)
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

from .models import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelectorKind,
    ObjectSetDefinition,
)
from .query_gateway import SecuredObjectSetQueryResult

_LOGGER = logging.getLogger(__name__)

RESOURCE_STATE_FUNCTION_NAME = "query.resource_state_inventory"
OBSERVATION_PENDING = "inventory_observation_pending"
COVERAGE_REF_PREFIX = "pending-state-coverage:"
_COVERAGE_STATE_KEY_PREFIX = "semantic-pending-state-coverage:"
_LIVE_SOURCE_IDENTITY = "azure.resource_manager.exact"
_FRESHNESS_CEILING_SECONDS = 300
_DIGEST = r"^sha256:[a-f0-9]{64}$"
_OVERLAY_STABLE = frozenset({"id", "type", "name", "parent_id", "location"})

_ELIGIBLE_NODES: ContextVar[frozenset[str]] = ContextVar(
    "fdai_pending_state_eligible_nodes", default=frozenset()
)
_PLAN_DIGEST: ContextVar[str | None] = ContextVar("fdai_pending_state_plan_digest", default=None)


def resource_type_constraint(predicates: Sequence[ObjectPredicate]) -> tuple[str, ...]:
    """Return the Resource types an exact ``type`` predicate limits a read to, or none."""

    for predicate in predicates:
        if predicate.property != "type":
            continue
        if predicate.operator is ObjectPredicateOperator.EQUALS and isinstance(
            predicate.equals, str
        ):
            return (predicate.equals,)
        if predicate.operator is ObjectPredicateOperator.IN and all(
            isinstance(value, str) for value in predicate.values
        ):
            return tuple(sorted({str(value) for value in predicate.values}))
    return ()


def certify_pending_state_shape(plan: OntologyQueryPlan) -> frozenset[str]:
    """Return the ObjectSet nodes whose only consumer is a terminal resource-state filter."""

    eligible: set[str] = set()
    for node in plan.nodes:
        if node.kind is not QueryNodeKind.OBJECT_SET:
            continue
        consumers = [item for item in plan.nodes if node.node_id in item.depends_on]
        if len(consumers) != 1:
            continue
        consumer = consumers[0]
        if (
            consumer.kind is not QueryNodeKind.FUNCTION
            or consumer.depends_on != (node.node_id,)
            or consumer.arguments.get("function_name") != RESOURCE_STATE_FUNCTION_NAME
            or any(consumer.node_id in item.depends_on for item in plan.nodes)
        ):
            continue
        try:
            definition = ObjectSetDefinition.model_validate(node.arguments.get("definition"))
        except ValueError:
            continue
        if (
            definition.selector.kind is not ObjectSelectorKind.OBJECT_TYPE
            or definition.selector.name != "Resource"
            or definition.traversal is not None
            or definition.include_relationships
            or definition.root_ids
            or definition.object_ids
            or not resource_type_constraint(definition.predicates)
            # The overlay rewrites provider properties after the store filtered on them, so a
            # predicate may only read properties the overlay never changes.
            or not all(_overlay_stable(item) for item in definition.predicates)
        ):
            continue
        eligible.add(node.node_id)
    return frozenset(eligible)


def _overlay_stable(predicate: ObjectPredicate) -> bool:
    # The overlay always keeps the state metadata key, so requiring it is overlay-invariant.
    return predicate.property in _OVERLAY_STABLE or (
        predicate.property == "properties"
        and predicate.operator is ObjectPredicateOperator.CONTAINS
        and predicate.equals == STATE_FACT_METADATA_PROPERTY
    )


@contextmanager
def pending_state_plan_scope(plan: OntologyQueryPlan) -> Iterator[None]:
    """Expose the certified eligible nodes and plan digest to handlers while the plan runs."""

    nodes_token = _ELIGIBLE_NODES.set(certify_pending_state_shape(plan))
    digest_token = _PLAN_DIGEST.set(_sha256(plan.model_dump(mode="json")))
    try:
        yield
    finally:
        _PLAN_DIGEST.reset(digest_token)
        _ELIGIBLE_NODES.reset(nodes_token)


def certified_plan_digest(node_id: str) -> str | None:
    """Return the running plan's digest when this node was certified eligible."""

    return _PLAN_DIGEST.get() if node_id in _ELIGIBLE_NODES.get() else None


@dataclass(frozen=True, slots=True)
class PendingObservation:
    """One unprojected object observation of a Resource type the read is limited to."""

    observation_id: str
    subject_ref: str
    subject_type: str
    provider_ref: str | None
    mutation_kind: str
    tombstone: bool
    effective_at: datetime


@dataclass(frozen=True, slots=True)
class PendingStateDescriptor:
    """The active generation and its pending observations from one consistent snapshot."""

    generation: str | None
    observations: tuple[PendingObservation, ...]
    overflow: bool


class PendingStateDescriptorUnavailableError(RuntimeError):
    """The pending descriptor could not be read; the partial result stays unchanged."""


class PendingStateDescriptorReader(Protocol):
    async def pending_state_descriptor(
        self,
        *,
        subject_types: Sequence[str],
        limit: int,
    ) -> PendingStateDescriptor: ...


@dataclass(frozen=True, slots=True)
class PendingStateSources:
    """Delivery adapters that let composition enable skew-bounded pending-state refresh."""

    descriptor_reader: PendingStateDescriptorReader
    state_reader: ExactResourceStateReader


class SecuredObjectSetMaterializer(Protocol):
    async def materialize(
        self,
        definition: ObjectSetDefinition,
        *,
        projection_request: ProjectionRequest,
        state_overlay: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> SecuredObjectSetQueryResult: ...


class LiveStateFact(ContractBase):
    """One authoritative live state that covers a pending subject in one answer."""

    resource_ref: str = Field(min_length=1, max_length=512)
    resource_type: str = Field(min_length=1, max_length=128)
    state: str = Field(min_length=1, max_length=128)
    provider_time: datetime
    received_at: datetime
    evidence_ref: str = Field(pattern=r"^arm-state:sha256:[a-f0-9]{64}$")
    observation_ids: tuple[str, ...] = Field(min_length=1, max_length=10)


class PendingStateCoverageReceipt(ContractBase):
    """Durable composite receipt that lets one answer cover its pending same-type updates."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    plan_digest: Annotated[str, Field(pattern=_DIGEST)]
    node_id: str = Field(min_length=1, max_length=128)
    ontology_release_digest: Annotated[str, Field(pattern=_DIGEST)]
    principal_scope_digest: Annotated[str, Field(pattern=_DIGEST)] | None = None
    source_generation: str | None = None
    first_cutoff: datetime
    second_cutoff: datetime
    pending_observation_ids: tuple[str, ...] = Field(min_length=1, max_length=10)
    facts: tuple[LiveStateFact, ...] = Field(min_length=1, max_length=10)
    result_digest: Annotated[str, Field(pattern=_DIGEST)]
    decision: Literal["covered"] = "covered"
    execution_authority: Literal[False] = False

    @property
    def digest(self) -> str:
        return _sha256(self.model_dump(mode="json"))


class CoverageStateStore(Protocol):
    async def write_state(self, key: str, value: dict[str, Any]) -> None: ...

    async def read_state(self, key: str) -> Mapping[str, Any] | None: ...


class PendingStateCoverageLedger:
    """Persist composite receipts durably and resolve them from a node's evidence references."""

    def __init__(self, *, store: CoverageStateStore, cache_size: int = 256) -> None:
        self._store = store
        self._cache_size = cache_size
        self._receipts: OrderedDict[str, PendingStateCoverageReceipt] = OrderedDict()

    async def record(self, receipt: PendingStateCoverageReceipt) -> str:
        digest = receipt.digest
        await self._store.write_state(
            f"{_COVERAGE_STATE_KEY_PREFIX}{digest}", receipt.model_dump(mode="json")
        )
        self._receipts[digest] = receipt
        while len(self._receipts) > self._cache_size:
            self._receipts.popitem(last=False)
        return f"{COVERAGE_REF_PREFIX}{digest}"

    async def coverage_argument(
        self, function_name: str, evidence_refs: Sequence[str]
    ) -> dict[str, Any] | None:
        """Return the receipt argument for the state function, when the node carries one."""

        if function_name != RESOURCE_STATE_FUNCTION_NAME:
            return None
        receipt = await self.resolve(evidence_refs)
        return receipt.model_dump(mode="json") if receipt is not None else None

    async def resolve(self, evidence_refs: Sequence[str]) -> PendingStateCoverageReceipt | None:
        refs = [ref for ref in evidence_refs if ref.startswith(COVERAGE_REF_PREFIX)]
        if len(refs) != 1:
            return None
        digest = refs[0].removeprefix(COVERAGE_REF_PREFIX)
        receipt = self._receipts.get(digest)
        if receipt is None:
            stored = await self._store.read_state(f"{_COVERAGE_STATE_KEY_PREFIX}{digest}")
            if stored is None:
                return None
            receipt = PendingStateCoverageReceipt.model_validate(dict(stored))
        # A receipt whose content no longer hashes to its reference is never admitted.
        return receipt if receipt.digest == digest else None


def coverage_admits(
    coverage: Mapping[str, Any] | None,
    secured: SecuredObjectSetQueryResult,
) -> bool:
    """Return whether a composite receipt completes this exact partial ObjectSet result."""

    if coverage is None:
        return False
    try:
        receipt = PendingStateCoverageReceipt.model_validate(dict(coverage))
    except ValueError:
        return False
    graph = secured.materialization.graph
    present = {record.id for record in graph.objects}
    covered = {fact.resource_ref for fact in receipt.facts}
    fact_observations = {item for fact in receipt.facts for item in fact.observation_ids}
    return (
        not secured.receipt.truncated
        and not graph.source_complete
        and graph.source_incomplete_reason == OBSERVATION_PENDING
        and receipt.result_digest == secured.receipt.projected_result_digest
        and receipt.source_generation == secured.receipt.source_generation
        and receipt.second_cutoff == secured.receipt.observation_cutoff
        and covered <= present
        and fact_observations == set(receipt.pending_observation_ids)
    )


class PendingStateRefresher:
    """Read pending subjects' authoritative state and materialize once more within the skew."""

    def __init__(
        self,
        *,
        gateway: SecuredObjectSetMaterializer,
        descriptor_reader: PendingStateDescriptorReader,
        state_reader: ExactResourceStateReader,
        ledger: PendingStateCoverageLedger,
        clock: Any = None,
        max_subjects: int = 10,
        read_timeout_seconds: float = 2.5,
        max_skew_seconds: float = 5.0,
        second_pass_seconds: float = 1.0,
        margin_seconds: float = 1.0,
    ) -> None:
        if not 1 <= max_subjects <= 10:
            raise ValueError("pending-state refresh covers at most ten subjects")
        self._gateway = gateway
        self._descriptor_reader = descriptor_reader
        self._state_reader = state_reader
        self._ledger = ledger
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_subjects = max_subjects
        self._read_timeout = read_timeout_seconds
        self._max_skew = max_skew_seconds
        self._second_pass = second_pass_seconds
        self._margin = margin_seconds

    async def cover(
        self,
        *,
        node_id: str,
        definition: ObjectSetDefinition,
        projection_request: ProjectionRequest,
        secured: SecuredObjectSetQueryResult,
    ) -> tuple[SecuredObjectSetQueryResult, tuple[str, ...]]:
        """Refresh, keeping the verified partial result when any live source fails."""

        try:
            return await self.refresh(
                node_id=node_id,
                definition=definition,
                projection_request=projection_request,
                secured=secured,
            )
        except (ValueError, PendingStateDescriptorUnavailableError) as exc:
            _LOGGER.warning(
                "pending_state_refresh_failed", extra={"error_type": type(exc).__name__}
            )
            return secured, ()

    async def refresh(
        self,
        *,
        node_id: str,
        definition: ObjectSetDefinition,
        projection_request: ProjectionRequest,
        secured: SecuredObjectSetQueryResult,
    ) -> tuple[SecuredObjectSetQueryResult, tuple[str, ...]]:
        """Return a covered second materialization and its references, or the input unchanged."""

        plan_digest = certified_plan_digest(node_id)
        graph = secured.materialization.graph
        if (
            plan_digest is None
            or graph.source_complete
            or graph.source_incomplete_reason != OBSERVATION_PENDING
            or secured.receipt.truncated
        ):
            return secured, ()
        types = resource_type_constraint(definition.predicates)
        descriptor = await self._descriptor_reader.pending_state_descriptor(
            subject_types=types, limit=self._max_subjects
        )
        subjects = self._eligible_subjects(descriptor, secured, types)
        if subjects is None:
            return secured, ()
        deadline = (
            (
                definition.as_of.astimezone(UTC) + timedelta(seconds=self._max_skew) - self._clock()
            ).total_seconds()
            - self._second_pass
            - self._margin
        )
        if deadline < 0.5:
            _LOGGER.info("pending_state_refresh_skipped", extra={"reason": "skew_budget"})
            return secured, ()
        readings = await self._read(subjects, deadline)
        if readings is None:
            return secured, ()
        received_at = self._clock()
        overlay: dict[str, dict[str, Any]] = {}
        facts: list[LiveStateFact] = []
        records = {record.id: record for record in graph.objects}
        for subject_ref, (latest, observations) in subjects.items():
            reading = readings[subject_ref]
            # A reading older than the pending change cannot prove the changed state.
            if reading is None or reading.provider_time < latest.effective_at:
                _LOGGER.info("pending_state_refresh_skipped", extra={"reason": "unproven_reading"})
                return secured, ()
            overlay[subject_ref] = _overlay_properties(
                records[subject_ref].properties, reading, received_at
            )
            facts.append(
                LiveStateFact(
                    resource_ref=subject_ref,
                    resource_type=reading.resource_type,
                    state=reading.state,
                    provider_time=reading.provider_time,
                    received_at=received_at,
                    evidence_ref=reading.evidence_ref,
                    observation_ids=tuple(sorted(item.observation_id for item in observations)),
                )
            )
        second = await self._gateway.materialize(
            definition, projection_request=projection_request, state_overlay=overlay
        )
        fenced = await self._descriptor_reader.pending_state_descriptor(
            subject_types=types, limit=self._max_subjects
        )
        second_graph = second.materialization.graph
        if (
            fenced != descriptor
            or second.receipt.truncated
            or second_graph.source_generation != graph.source_generation
            or second_graph.source_incomplete_reason != OBSERVATION_PENDING
            or {(item.id, item.object_type) for item in second_graph.objects}
            != {(item.id, item.object_type) for item in graph.objects}
        ):
            _LOGGER.info("pending_state_refresh_skipped", extra={"reason": "fence_changed"})
            return secured, ()
        receipt = PendingStateCoverageReceipt(
            plan_digest=plan_digest,
            node_id=node_id,
            ontology_release_digest=second.receipt.ontology_release.digest,
            principal_scope_digest=projection_request.principal_scope_digest,
            source_generation=second.receipt.source_generation,
            first_cutoff=secured.receipt.observation_cutoff,
            second_cutoff=second.receipt.observation_cutoff,
            pending_observation_ids=tuple(
                sorted(item.observation_id for item in descriptor.observations)
            ),
            facts=tuple(facts),
            result_digest=second.receipt.projected_result_digest,
        )
        reference = await self._ledger.record(receipt)
        _LOGGER.info(
            "pending_state_refresh_covered",
            extra={"subjects": len(facts), "observations": len(descriptor.observations)},
        )
        return second, (reference, *(fact.evidence_ref for fact in facts))

    def _eligible_subjects(
        self,
        descriptor: PendingStateDescriptor,
        secured: SecuredObjectSetQueryResult,
        types: Sequence[str],
    ) -> dict[str, tuple[PendingObservation, list[PendingObservation]]] | None:
        if descriptor.overflow or not descriptor.observations:
            return None
        if descriptor.generation != secured.receipt.source_generation:
            return None
        present = {record.id for record in secured.materialization.graph.objects}
        grouped: dict[str, tuple[PendingObservation, list[PendingObservation]]] = {}
        for item in descriptor.observations:
            if (
                item.tombstone
                or item.mutation_kind != "upsert"
                or item.subject_ref not in present
                or item.subject_type not in types
                or not item.provider_ref
                or not self._state_reader.supports(item.subject_type)
            ):
                return None
            latest, observations = grouped.get(item.subject_ref, (item, []))
            if latest.provider_ref != item.provider_ref:
                return None
            observations.append(item)
            newest = item if item.effective_at > latest.effective_at else latest
            grouped[item.subject_ref] = (newest, observations)
        return grouped

    async def _read(
        self,
        subjects: Mapping[str, tuple[PendingObservation, list[PendingObservation]]],
        deadline: float,
    ) -> dict[str, ExactResourceStateReading | None] | None:
        timeout = min(self._read_timeout, deadline)

        async def read(
            subject_ref: str, latest: PendingObservation
        ) -> ExactResourceStateReading | None:
            return await self._state_reader.read_state(
                resource_ref=subject_ref,
                resource_type=latest.subject_type,
                provider_ref=str(latest.provider_ref),
                timeout_seconds=timeout,
            )

        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *(read(subject_ref, latest) for subject_ref, (latest, _) in subjects.items())
                ),
                timeout=deadline,
            )
        except (TimeoutError, ExactResourceStateUnavailableError):
            _LOGGER.info("pending_state_refresh_skipped", extra={"reason": "read_unavailable"})
            return None
        return dict(zip(subjects, results, strict=True))


def _overlay_properties(
    properties: Mapping[str, Any],
    reading: ExactResourceStateReading,
    received_at: datetime,
) -> dict[str, Any]:
    provider = dict(properties.get("properties") or {})
    provider["state"] = reading.state
    metadata = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity=_LIVE_SOURCE_IDENTITY,
        source_revision=reading.evidence_ref,
        effective_at=reading.provider_time,
        recorded_at=max(received_at, reading.provider_time),
        evidence_cutoff=reading.provider_time,
        freshness_ceiling_seconds=_FRESHNESS_CEILING_SECONDS,
        completeness=1.0,
        synthetic=False,
        evidence_refs=(reading.evidence_ref,),
    ).to_mapping()
    root = provider.get(STATE_FACT_METADATA_PROPERTY)
    existing = dict(root) if isinstance(root, Mapping) and "lane" not in root else {}
    provider[STATE_FACT_METADATA_PROPERTY] = {**existing, "state": metadata}
    return provider


def _sha256(value: object) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def bind_pending_state(
    sources: PendingStateSources | None,
    *,
    gateway: SecuredObjectSetMaterializer,
    store: CoverageStateStore | None,
    clock: Any,
) -> tuple[PendingStateRefresher | None, PendingStateCoverageLedger | None]:
    """Bind the refresher and its ledger, or neither when the venue has not enabled them."""

    if sources is None or store is None:
        return None, None
    ledger = PendingStateCoverageLedger(store=store)
    refresher = PendingStateRefresher(
        gateway=gateway,
        descriptor_reader=sources.descriptor_reader,
        state_reader=sources.state_reader,
        ledger=ledger,
        clock=clock,
    )
    return refresher, ledger


__all__ = [
    "COVERAGE_REF_PREFIX",
    "LiveStateFact",
    "PendingObservation",
    "PendingStateCoverageLedger",
    "PendingStateCoverageReceipt",
    "PendingStateDescriptor",
    "PendingStateDescriptorReader",
    "PendingStateDescriptorUnavailableError",
    "PendingStateRefresher",
    "PendingStateSources",
    "bind_pending_state",
    "certified_plan_digest",
    "certify_pending_state_shape",
    "coverage_admits",
    "pending_state_plan_scope",
    "resource_type_constraint",
]
