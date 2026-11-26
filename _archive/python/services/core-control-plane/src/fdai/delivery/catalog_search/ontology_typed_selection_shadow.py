"""Runtime shadow observation of agreement-gated typed instance selection.

Shadow mode never changes a returned answer. The answer path fixes its outcome first and then
enqueues a detached, budgeted observation through a no-throw boundary. Two independent proposals
are verified against current ObjectSet membership at one captured ``as_of`` and gated with the
qualification rule: retrieved identity sets must be equal, and a clarification retrieves nothing.
Runtime protocol ``typed-selection-runtime-shadow.v1`` is one K=2 decision per invocation, so its
figures relate to, but never replace, ``agreement-gated-pooled-qualification.v1`` (K=2, R=3).

Every started observation retains a write-once intent row before any provider call and a terminal
row with a typed outcome. An intent without a terminal row is a lost observation. Rows carry no
execution authority and hold query digests, not query text. Promotion is not representable here.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal, get_args

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform import QueryManifest
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.shared.providers.state_store import StateStore

from .generation import SemanticGenerationBuild
from .ontology_candidate_proposal import (
    OntologyCandidateModelBinding,
    OntologyCandidateProposer,
    candidate_proposal_payload,
)
from .ontology_candidate_reader import (
    OntologyCandidateSearchResult,
    OntologyInstanceCandidateReader,
)
from .ontology_candidate_selection import OntologyCandidateClause, OntologyCandidateSelection
from .ontology_index_lifecycle import IndexPointer, IndexScope
from .ontology_semantic_qualification import PROTOCOL_ID as QUALIFICATION_PROTOCOL_ID
from .ontology_snapshot_store import OntologyGenerationSnapshotStore, OntologyStagedProjection

_LOGGER = logging.getLogger(__name__)

RUNTIME_PROTOCOL_ID = "typed-selection-runtime-shadow.v1"
SHADOW_SCHEMA_VERSION = "1.0.0"
SHADOW_INTENT_PREFIX = "ontology-typed-selection-shadow-intent:v1:"
SHADOW_TERMINAL_PREFIX = "ontology-typed-selection-shadow:v1:"
SHADOW_QUOTA_PREFIX = "ontology-typed-selection-shadow-quota:v1:"
PASSES_PER_DECISION = 2
_QUOTA_ATTEMPTS = 8
_CANCEL_RECORD_SECONDS = 2.0

ShadowUnavailableReason = Literal[
    "index_unavailable",
    "index_changed",
    "source_drift",
    "context_unavailable",
    "proposal_unavailable",
    "proposal_binding_changed",
    "membership_unavailable",
    "deadline_exceeded",
    "cancelled",
]
_REASON_ORDER: tuple[ShadowUnavailableReason, ...] = get_args(ShadowUnavailableReason)
ShadowGatedOutcome = Literal["selected", "empty", "disagreed", "unavailable"]
ShadowComparison = Literal[
    "same_membership",
    "different_membership",
    "shadow_empty",
    "shadow_disagreed",
    "primary_unavailable",
    "shadow_unavailable",
]
ShadowSkipReason = Literal[
    "shadow_capacity",
    "shadow_budget_exhausted",
    "principal_budget_exhausted",
    "schedule_failed",
    "observation_unrecorded",
]


class _ShadowUnavailableError(Exception):
    def __init__(self, reason: ShadowUnavailableReason, *, failure_type: str | None = None) -> None:
        super().__init__(reason)
        self.reason: ShadowUnavailableReason = reason
        self.failure_type = failure_type


@dataclass(slots=True)
class _Progress:
    """Evidence gathered so far; a failure keeps what completed before it."""

    target: ShadowTarget | None = None
    binding: OntologyCandidateModelBinding | None = None
    as_of: datetime | None = None
    passes: list[_Pass] = field(default_factory=list)
    failure_types: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TypedSelectionShadowBudget:
    """Per-observation deadline, process concurrency, and durable deployment quotas."""

    total_timeout_seconds: float = 30.0
    max_concurrent: int = 1
    max_observations_per_hour: int = 30
    max_principal_observations_per_hour: int = 10
    retain_newest: int = 2_000

    def __post_init__(self) -> None:
        if (
            not 0 < self.total_timeout_seconds <= 30
            or not 1 <= self.max_concurrent <= 4
            or not 1 <= self.max_observations_per_hour <= 600
            or not 1 <= self.max_principal_observations_per_hour <= self.max_observations_per_hour
            or not 1 <= self.retain_newest <= 10_000
        ):
            raise ValueError("typed selection shadow budget must stay bounded")


@dataclass(frozen=True, slots=True)
class TypedSelectionShadowBinding:
    """Composition-supplied proposer for shadow evidence; it grants no answer authority."""

    proposer: OntologyCandidateProposer
    data_handling_policy_digest: str
    expected_binding: OntologyCandidateModelBinding
    budget: TypedSelectionShadowBudget | None = None


@dataclass(frozen=True, slots=True)
class ShadowPrimaryAnswer:
    """The already-fixed answer-path outcome the shadow is compared with."""

    outcome: Literal["returned", "unavailable"]
    score_kind: str | None = None
    returned_document_ids: tuple[str, ...] = ()
    matched_candidate_count: int | None = None
    truncated: bool | None = None
    result_digest: str | None = None
    failure_type: str | None = None

    @classmethod
    def returned(
        cls, result: OntologyCandidateSearchResult, *, result_digest: str
    ) -> ShadowPrimaryAnswer:
        return cls(
            outcome="returned",
            score_kind=result.score_kind,
            returned_document_ids=tuple(item[0] for item in result.scores),
            matched_candidate_count=result.matched_candidate_count,
            truncated=result.truncated,
            result_digest=result_digest,
        )

    @classmethod
    def unavailable(cls, failure: BaseException) -> ShadowPrimaryAnswer:
        return cls(outcome="unavailable", failure_type=type(failure).__name__)


@dataclass(frozen=True, slots=True)
class ShadowTarget:
    """Current sealed pointer plus the principal-bound source for one observation."""

    pointer: IndexPointer
    staged: OntologyStagedProjection
    manifest: QueryManifest
    gateway: SecuredObjectSetQueryGateway


ShadowTargetResolver = Callable[[IndexScope], Awaitable[ShadowTarget]]
ShadowTargetCurrent = Callable[[IndexScope, ShadowTarget], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class ShadowInvocation:
    """One eligible answer-path invocation, identified without retaining its text."""

    query: str
    limit: int
    scope: IndexScope
    primary: ShadowPrimaryAnswer
    request_ref: str | None = None


@dataclass(frozen=True, slots=True)
class _Pass:
    record: dict[str, object]
    retrieved: frozenset[str]
    status: Literal["select", "clarify"]


class TypedSelectionShadowObserver:
    """Run budgeted K=2 shadow observations off the answer path and retain evidence.

    The observer owns no answer, reader cache, pointer, enrollment, or authority. It only reads
    current sources, calls the bound proposer, and writes its own evidence and quota rows.
    """

    def __init__(
        self,
        *,
        proposer: OntologyCandidateProposer,
        reader: OntologyInstanceCandidateReader,
        snapshots: OntologyGenerationSnapshotStore,
        store: StateStore,
        clock: Callable[[], datetime],
        data_handling_policy_digest: str,
        expected_binding: OntologyCandidateModelBinding | None = None,
        budget: TypedSelectionShadowBudget | None = None,
    ) -> None:
        if not data_handling_policy_digest.startswith("sha256:"):
            raise ValueError("typed selection shadow requires a reviewed data-handling policy")
        self._proposer, self._reader, self._snapshots, self._store = (
            proposer,
            reader,
            snapshots,
            store,
        )
        self._clock = clock
        self._policy_digest = data_handling_policy_digest
        self._expected_binding = expected_binding
        self._budget = budget or TypedSelectionShadowBudget()
        self._tasks: set[asyncio.Task[None]] = set()
        self._skipped: dict[ShadowSkipReason, int] = {
            "shadow_capacity": 0,
            "shadow_budget_exhausted": 0,
            "principal_budget_exhausted": 0,
            "schedule_failed": 0,
            "observation_unrecorded": 0,
        }

    @property
    def skipped(self) -> dict[str, int]:
        """Eligible invocations not observed since the last intent row, by typed reason."""
        return {str(name): count for name, count in self._skipped.items()}

    @property
    def in_flight(self) -> int:
        return len(self._tasks)

    def schedule(
        self,
        invocation: ShadowInvocation,
        *,
        resolve: ShadowTargetResolver,
        current: ShadowTargetCurrent,
    ) -> asyncio.Task[None] | None:
        """Enqueue one detached observation; never awaits, blocks, or raises."""
        try:
            if len(self._tasks) >= self._budget.max_concurrent:
                self._skipped["shadow_capacity"] += 1
                return None
            task = asyncio.get_running_loop().create_task(
                self._run(invocation, resolve=resolve, current=current),
                name="ontology-typed-selection-shadow",
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        except Exception as exc:  # noqa: BLE001 - shadow scheduling never affects the answer
            self._skipped["schedule_failed"] += 1
            _LOGGER.warning(
                "ontology_typed_selection_shadow_unscheduled",
                extra={"failure_type": type(exc).__name__},
            )
            return None
        return task

    async def wait_idle(self) -> None:
        """Wait for in-flight observations without cancelling them; never raises their errors."""
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def aclose(self) -> None:
        """Cancel in-flight observations; each attempts a bounded `cancelled` terminal row."""
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(
        self,
        invocation: ShadowInvocation,
        *,
        resolve: ShadowTargetResolver,
        current: ShadowTargetCurrent,
    ) -> None:
        try:
            await self.observe(invocation, resolve=resolve, current=current)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - shadow failure is evidence loss, not an answer
            self._skipped["observation_unrecorded"] += 1
            _LOGGER.warning(
                "ontology_typed_selection_shadow_unrecorded",
                extra={"failure_type": type(exc).__name__},
            )

    async def observe(
        self,
        invocation: ShadowInvocation,
        *,
        resolve: ShadowTargetResolver,
        current: ShadowTargetCurrent,
    ) -> dict[str, object] | None:
        """Claim quota, record intent, observe once, and retain one terminal row.

        Returns ``None`` when the durable quota is exhausted; that skip is counted and reported
        in the next intent row.
        """
        scope = invocation.scope
        if not await self._claim("deployment", self._budget.max_observations_per_hour):
            self._skipped["shadow_budget_exhausted"] += 1
            return None
        if not await self._claim(
            f"principal:{scope.principal_scope_digest}",
            self._budget.max_principal_observations_per_hour,
        ):
            self._skipped["principal_budget_exhausted"] += 1
            return None
        loop = asyncio.get_running_loop()
        observation_id = uuid.uuid4().hex
        started_at, started = self._clock(), loop.time()
        intent: dict[str, object] = {
            "schema_version": SHADOW_SCHEMA_VERSION,
            "observation_id": observation_id,
            "protocol_id": RUNTIME_PROTOCOL_ID,
            "scope_digest": scope.digest,
            "principal_scope_digest": scope.principal_scope_digest,
            "query_digest": content_digest({"query": invocation.query}),
            "request_ref": invocation.request_ref,
            "data_handling_policy_digest": self._policy_digest,
            "skipped_before": dict(self._skipped),
            "started_at": started_at.isoformat(),
        }
        await self._write(SHADOW_INTENT_PREFIX, observation_id, intent)
        for name in self._skipped:
            self._skipped[name] = 0
        progress = _Progress()
        reason: ShadowUnavailableReason | None = None
        try:
            async with asyncio.timeout(self._budget.total_timeout_seconds):
                await self._observe(invocation, resolve, progress)
                if progress.target is None or not await current(scope, progress.target):
                    raise _ShadowUnavailableError("index_changed")
        except _ShadowUnavailableError as exc:
            reason = exc.reason
            if exc.failure_type is not None:
                progress.failure_types.append(exc.failure_type)
        except TimeoutError:
            reason = "deadline_exceeded"
        except asyncio.CancelledError:
            terminal = self._terminal(intent, invocation, progress, "cancelled", started)
            try:
                async with asyncio.timeout(_CANCEL_RECORD_SECONDS):
                    await asyncio.shield(
                        self._write(SHADOW_TERMINAL_PREFIX, observation_id, terminal)
                    )
            except (Exception, asyncio.CancelledError):  # noqa: BLE001 - shutdown is best effort
                _LOGGER.warning("ontology_typed_selection_shadow_cancel_unrecorded")
            raise
        terminal = self._terminal(intent, invocation, progress, reason, started)
        await self._write(SHADOW_TERMINAL_PREFIX, observation_id, terminal)
        return terminal

    def _terminal(
        self,
        intent: Mapping[str, object],
        invocation: ShadowInvocation,
        progress: _Progress,
        reason: ShadowUnavailableReason | None,
        started: float,
    ) -> dict[str, object]:
        target, binding, as_of, passes = (
            progress.target,
            progress.binding,
            progress.as_of,
            progress.passes,
        )
        outcome = _gate(passes) if reason is None else "unavailable"
        selected = passes[0].retrieved if outcome in {"selected", "empty"} else frozenset()
        body: dict[str, object] = {
            **intent,
            "qualification_protocol_id": QUALIFICATION_PROTOCOL_ID,
            "mode": "shadow",
            "passes_per_decision": PASSES_PER_DECISION,
            "answer_changed": False,
            "authority": "candidate_only",
            "execution_authority": False,
            "limit": invocation.limit,
            "as_of": as_of.isoformat() if as_of is not None else None,
            "target": _target_record(target),
            "proposer_binding": _binding_record(binding),
            "primary": asdict(invocation.primary),
            "passes": [item.record for item in passes],
            "status_agreement": len(passes) == PASSES_PER_DECISION
            and len({item.status for item in passes}) == 1,
            "gated_outcome": outcome,
            "unavailable_reason": reason,
            "failure_types": sorted(progress.failure_types),
            "gated_document_ids": sorted(selected),
            "comparison": _compare(invocation.primary, outcome, selected),
            "completed_at": self._clock().isoformat(),
            "latency_ms": round((asyncio.get_running_loop().time() - started) * 1000, 3),
        }
        return {**body, "record_digest": content_digest(body)}

    async def _write(self, prefix: str, observation_id: str, value: dict[str, object]) -> None:
        if not await self._store.write_state_if_absent(f"{prefix}{observation_id}", value):
            raise ValueError("typed selection shadow observation identity collided")
        await self._store.delete_states_beyond(prefix, retain_newest=self._budget.retain_newest)

    async def _claim(self, subject: str, limit: int) -> bool:
        """Atomically consume one slot of a durable hourly quota shared across replicas."""
        hour = self._clock().strftime("%Y%m%dT%H")
        key = f"{SHADOW_QUOTA_PREFIX}{hour}:{content_digest({'subject': subject})}"
        for _attempt in range(_QUOTA_ATTEMPTS):
            stored: Mapping[str, Any] | None = await self._store.read_state(key)
            used = int(stored.get("revision", 0)) if stored is not None else 0
            if used >= limit:
                return False
            if await self._store.compare_and_set_state(
                key, {"revision": used + 1, "hour": hour, "limit": limit}, expected_revision=used
            ):
                await self._store.delete_states_beyond(SHADOW_QUOTA_PREFIX, retain_newest=256)
                return True
        return False

    async def _observe(
        self,
        invocation: ShadowInvocation,
        resolve: ShadowTargetResolver,
        progress: _Progress,
    ) -> None:
        try:
            target = await resolve(invocation.scope)
            active = target.pointer.active
            build = await self._snapshots.read(
                target.staged.snapshot_digest,
                manifest=target.manifest,
                source_generation=target.staged.source_generation,
                source_projection_digest=target.staged.source_projection_digest,
            )
        except (ValueError, PermissionError, LookupError) as exc:
            raise _ShadowUnavailableError(
                "index_unavailable", failure_type=type(exc).__name__
            ) from exc
        progress.target = target
        if (
            active is None
            or build is None
            or build.metadata.generation_digest != active.generation_digest
        ):
            raise _ShadowUnavailableError("index_unavailable")
        try:
            binding = self._proposer.candidate_proposal_binding()
        except (ValueError, TypeError) as exc:
            raise _ShadowUnavailableError("proposal_binding_changed") from exc
        progress.binding = binding
        if self._expected_binding is not None and binding != self._expected_binding:
            raise _ShadowUnavailableError("proposal_binding_changed")
        try:
            payload = candidate_proposal_payload(
                query=invocation.query,
                manifest=target.manifest,
                build=build,
                staged=target.staged,
            )
        except ValueError as exc:
            raise _ShadowUnavailableError(
                "context_unavailable", failure_type=type(exc).__name__
            ) from exc
        input_digest = str(payload["input_digest"])
        # Both proposals finish before membership: a sibling failure never hides a proposal,
        # and one as_of captured afterwards stays inside the gateway's current-state skew.
        results = await asyncio.gather(
            *(
                self._propose(index, invocation, target, build, input_digest)
                for index in range(PASSES_PER_DECISION)
            ),
            return_exceptions=True,
        )
        failures: list[_ShadowUnavailableError] = []
        proposals: list[_Proposed] = []
        for item in results:
            if isinstance(item, _ShadowUnavailableError):
                failures.append(item)
            elif isinstance(item, BaseException):
                raise item
            else:
                proposals.append(item)
        progress.passes.extend(item.done for item in proposals if item.done is not None)
        if failures:
            progress.passes.extend(
                _Pass({**item.record, "membership": "not_attempted"}, frozenset(), "select")
                for item in proposals
                if item.done is None
            )
            progress.failure_types.extend(
                item.failure_type for item in failures if item.failure_type is not None
            )
            raise _ShadowUnavailableError(
                min((item.reason for item in failures), key=_REASON_ORDER.index)
            )
        progress.as_of = as_of = self._clock()
        for item in proposals:
            if item.done is None:
                progress.passes.append(await self._membership(item, invocation, target, as_of))
        progress.passes.sort(key=lambda item: int(str(item.record["pass_index"])))

    async def _propose(
        self,
        index: int,
        invocation: ShadowInvocation,
        target: ShadowTarget,
        build: SemanticGenerationBuild,
        input_digest: str,
    ) -> _Proposed:
        loop = asyncio.get_running_loop()
        started = loop.time()
        query = invocation.query
        try:
            proposed = await self._proposer.propose_candidate_selection(
                query=query, manifest=target.manifest, build=build, staged=target.staged
            )
            proposed.proposal.validate_source_quotes(query)
        except Exception as exc:  # noqa: BLE001 - every provider failure is one typed outcome
            raise _ShadowUnavailableError(
                "proposal_unavailable", failure_type=type(exc).__name__
            ) from exc
        if proposed.input_digest != input_digest:
            raise _ShadowUnavailableError("proposal_binding_changed")
        proposal = proposed.proposal
        record: dict[str, object] = {
            "pass_index": index,
            "input_digest": proposed.input_digest,
            "proposal_digest": content_digest(proposal.model_dump(mode="json")),
            "status": proposal.status,
            "reason": proposal.reason,
            "clause_count": len(proposal.clauses),
            "clause_shapes": [_clause_shape(clause) for clause in proposal.clauses],
            "quote_invalid_clauses": proposed.quote_invalid_clauses,
            "proposal_latency_ms": round((loop.time() - started) * 1000, 3),
        }
        if proposal.status == "clarify":
            if proposed.selection is not None:
                raise _ShadowUnavailableError("proposal_binding_changed")
            return _Proposed(record, None, _Pass(record, frozenset(), "clarify"))
        expected = OntologyCandidateSelection.bind(
            query=query, manifest=target.manifest, staged=target.staged, clauses=proposal.clauses
        )
        if proposed.selection != expected:
            raise _ShadowUnavailableError("proposal_binding_changed")
        return _Proposed(record, expected, None)

    async def _membership(
        self,
        proposed: _Proposed,
        invocation: ShadowInvocation,
        target: ShadowTarget,
        as_of: datetime,
    ) -> _Pass:
        record, selection = proposed.record, proposed.selection
        if selection is None:
            raise _ShadowUnavailableError("proposal_binding_changed")
        try:
            result = await self._reader.shadow_select(
                invocation.query,
                staged=target.staged,
                manifest=target.manifest,
                gateway=target.gateway,
                as_of=as_of,
                selection=selection,
                limit=invocation.limit,
            )
        except (ValueError, PermissionError, TimeoutError, LookupError) as exc:
            raise _ShadowUnavailableError(
                "membership_unavailable", failure_type=type(exc).__name__
            ) from exc
        authorized = result.authorized
        if result.score_kind != "predicate_membership" or authorized is None:
            raise _ShadowUnavailableError("membership_unavailable")
        if (
            authorized.snapshot_digest != target.staged.snapshot_digest
            or authorized.source_generation != target.staged.source_generation
            or authorized.principal_scope_digest != invocation.scope.principal_scope_digest
            or not authorized.query_receipt_digests
        ):
            raise _ShadowUnavailableError("source_drift")
        ids = tuple(item[0] for item in result.scores)
        record.update(
            {
                "selection_digest": result.selection_digest,
                "membership_document_ids": list(ids),
                "matched_candidate_count": result.matched_candidate_count,
                "truncated": result.truncated,
                "query_receipt_digests": list(authorized.query_receipt_digests),
                "authorized_result_digest": authorized.result_digest,
            }
        )
        return _Pass(record, frozenset(ids), "select")


@dataclass(frozen=True, slots=True)
class _Proposed:
    record: dict[str, object]
    selection: OntologyCandidateSelection | None
    done: _Pass | None


def _clause_shape(clause: OntologyCandidateClause) -> dict[str, object]:
    """Schema identifiers only; operands may quote the operator and are never retained."""
    return {
        "object_type": clause.object_type,
        "predicates": [[item.property, str(item.operator)] for item in clause.predicates],
        "nested_predicates": [
            [item.property, item.key, str(item.operator)] for item in clause.nested_predicates
        ],
        "object_id_count": len(clause.object_ids or ()),
    }


def _gate(passes: list[_Pass]) -> ShadowGatedOutcome:
    """Apply the qualification agreement rule: equal retrieved sets, clarify retrieves none."""
    if len(passes) != PASSES_PER_DECISION:
        return "unavailable"
    if any(item.retrieved != passes[0].retrieved for item in passes):
        return "disagreed"
    return "selected" if passes[0].retrieved else "empty"


def _compare(
    primary: ShadowPrimaryAnswer,
    outcome: ShadowGatedOutcome,
    selected: frozenset[str],
) -> ShadowComparison:
    if outcome == "unavailable":
        return "shadow_unavailable"
    if primary.outcome == "unavailable":
        return "primary_unavailable"
    if outcome == "disagreed":
        return "shadow_disagreed"
    if outcome == "empty":
        return "shadow_empty"
    if frozenset(primary.returned_document_ids) == selected:
        return "same_membership"
    return "different_membership"


def _target_record(target: ShadowTarget | None) -> dict[str, object] | None:
    if target is None or target.pointer.active is None:
        return None
    active = target.pointer.active
    return {
        "pointer_revision": target.pointer.revision,
        "active_generation_digest": active.digest,
        "generation_digest": active.generation_digest,
        "snapshot_digest": target.staged.snapshot_digest,
        "source_generation": target.staged.source_generation,
        "manifest_digest": target.manifest.manifest_digest,
        "ontology_release_digest": target.manifest.release_digest,
    }


def _binding_record(binding: OntologyCandidateModelBinding | None) -> dict[str, object] | None:
    if binding is None:
        return None
    return {
        "binding_digest": content_digest(asdict(binding)),
        "target_digest": binding.target_digest,
        "deployment_digest": binding.deployment_digest,
        "request_parameters_digest": binding.request_parameters_digest,
        "prompt_manifest_digest": content_digest(asdict(binding.prompt_manifest)),
    }
