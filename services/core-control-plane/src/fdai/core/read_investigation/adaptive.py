"""Bounded adaptive investigation over verified ontology read plans."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform.query_execution import OntologyQueryPlanExecutor
from fdai.core.ontology_platform.query_verification import OntologyQueryPlanVerifier
from fdai.core.rca.discrimination import (
    DiscriminatingObservationCandidate,
    HypothesisDiscriminationFrame,
    HypothesisDiscriminationSelection,
    build_hypothesis_discrimination_frame,
    select_discriminating_observation,
)
from fdai.core.rca.discrimination_shadow import (
    DiscriminationSelector,
    DiscriminationShadowComparison,
    run_discrimination_shadow,
)

from .adaptive_contract import (
    AdaptiveInvestigationBudget,
    AdaptiveInvestigationDisposition,
    AdaptiveInvestigationIteration,
    AdaptiveInvestigationResult,
    AdaptiveObservationExecution,
    AdaptiveQueryAuthorityContext,
    HypothesisRevisionSet,
    VerifiedObservationPlanBinding,
    build_adaptive_investigation_iteration,
    build_adaptive_investigation_result,
    build_adaptive_observation_execution,
    execution_result_digest,
    validate_query_manifest_snapshot,
)

_WORKFLOW_VERSION = "1.0.0"
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AdaptiveRoundProposal:
    """Complete candidate and verified-plan set for one frozen frame."""

    frame_digest: str
    candidates: tuple[DiscriminatingObservationCandidate, ...]
    bindings: tuple[VerifiedObservationPlanBinding, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.candidates, tuple) or not isinstance(self.bindings, tuple):
            raise ValueError("adaptive round candidates and bindings MUST be immutable tuples")
        if len(self.candidates) != len(self.bindings):
            raise ValueError("adaptive round requires one plan binding per candidate")
        if any(candidate.frame_digest != self.frame_digest for candidate in self.candidates):
            raise ValueError("adaptive round candidate does not match the frame")
        if any(binding.frame_digest != self.frame_digest for binding in self.bindings):
            raise ValueError("adaptive round query binding does not match the frame")
        receipt_digests = tuple(item.verification_receipt_digest for item in self.bindings)
        if len(receipt_digests) != len(set(receipt_digests)):
            raise ValueError("adaptive round query bindings MUST be unique")
        if {candidate.verified_query_receipt_digest for candidate in self.candidates} != set(
            receipt_digests
        ):
            raise ValueError("adaptive candidates do not match the verified query binding set")
        binding_costs = {
            item.verification_receipt_digest: item.cost_units for item in self.bindings
        }
        if any(
            candidate.cost_units != binding_costs[candidate.verified_query_receipt_digest]
            for candidate in self.candidates
        ):
            raise ValueError("adaptive candidate cost does not match its verified query plan")

    def binding_for(
        self,
        candidate: DiscriminatingObservationCandidate,
    ) -> VerifiedObservationPlanBinding:
        """Return the exact verified plan named by one candidate."""

        for binding in self.bindings:
            if binding.verification_receipt_digest == candidate.verified_query_receipt_digest:
                return binding
        raise ValueError("selected observation has no verified query plan binding")


class AdaptiveRoundSource(Protocol):
    """Build one complete candidate set from a frozen causal frame."""

    async def propose(
        self,
        frame: HypothesisDiscriminationFrame,
    ) -> AdaptiveRoundProposal: ...


class AdaptiveHypothesisReviser(Protocol):
    """Ask Forseti's boundary for one complete post-observation revision set."""

    async def revise(
        self,
        *,
        frame: HypothesisDiscriminationFrame,
        execution: AdaptiveObservationExecution,
    ) -> HypothesisRevisionSet: ...


class AdaptiveIterationSink(Protocol):
    """Persist one append-only iteration without deciding its contents."""

    async def record(self, iteration: AdaptiveInvestigationIteration) -> None: ...


class AdaptiveTerminalSink(Protocol):
    """Persist one terminal session receipt without changing its disposition."""

    async def record(self, result: AdaptiveInvestigationResult) -> None: ...


class AdaptiveShadowComparisonSink(Protocol):
    """Persist one authority-free active/challenger comparison."""

    async def record(self, comparison: DiscriminationShadowComparison) -> None: ...


Selector = Callable[
    [
        HypothesisDiscriminationFrame,
        tuple[DiscriminatingObservationCandidate, ...],
    ],
    HypothesisDiscriminationSelection,
]
PendingShadowPersistence = tuple[str, asyncio.Task[None]]


class VerifiedObservationGateway:
    """Verify and execute one candidate-bound read plan as one fail-closed operation."""

    def __init__(
        self,
        *,
        verifier: OntologyQueryPlanVerifier,
        executor: OntologyQueryPlanExecutor,
        authority: AdaptiveQueryAuthorityContext,
    ) -> None:
        self._verifier = verifier
        self._executor = executor
        self._authority = authority

    async def execute(
        self,
        *,
        round_index: int,
        frame: HypothesisDiscriminationFrame,
        selection: HypothesisDiscriminationSelection,
        candidate: DiscriminatingObservationCandidate,
        binding: VerifiedObservationPlanBinding,
        cancelled: asyncio.Event,
    ) -> AdaptiveObservationExecution:
        """Re-verify exact lineage before the executor can perform provider I/O."""

        if cancelled.is_set():
            raise asyncio.CancelledError
        if selection.selected_candidate_id != candidate.candidate_id:
            raise ValueError("query candidate does not match the active selection")
        if candidate.frame_digest != frame.frame_digest:
            raise ValueError("query candidate does not match the active frame")
        if binding.frame_digest != frame.frame_digest:
            raise ValueError("query binding does not match the active frame")
        if candidate.verified_query_receipt_digest != binding.verification_receipt_digest:
            raise ValueError("query candidate does not match the verification receipt")
        authority = self._authority
        validate_query_manifest_snapshot(authority.manifest)
        if binding.manifest.release_digest != authority.manifest.release_digest:
            raise ValueError("query binding targets a stale ontology release")
        if binding.manifest.manifest_digest != authority.manifest.manifest_digest:
            raise ValueError("query binding targets a stale query manifest")
        if binding.principal_scope_digest != authority.principal_scope_digest:
            raise PermissionError("query binding principal scope changed")
        if binding.plan.caller_role != authority.caller_role:
            raise PermissionError("query binding caller role changed")
        if binding.plan.purpose != authority.purpose:
            raise PermissionError("query binding purpose changed")
        verified = self._verifier.verify(binding.plan, manifest=authority.manifest)
        execution = await self._executor.execute(
            verified,
            expected_release_digest=authority.manifest.release_digest,
            expected_manifest_digest=authority.manifest.manifest_digest,
            expected_role=authority.caller_role,
            expected_purpose=authority.purpose,
            cancelled=cancelled,
        )
        evidence_refs = tuple(
            sorted(
                {reference for receipt in execution.receipts for reference in receipt.evidence_refs}
            )
        )
        return build_adaptive_observation_execution(
            round_index=round_index,
            frame_digest=frame.frame_digest,
            selection_digest=selection.selection_digest,
            candidate_digest=candidate.candidate_digest,
            binding_digest=binding.binding_digest,
            verification_receipt_digest=binding.verification_receipt_digest,
            plan_digest=verified.plan_digest,
            result_digest=execution_result_digest(execution),
            query_status=execution.status,
            evidence_refs=evidence_refs,
            reserved_cost_units=binding.cost_units,
            actual_cost_units=None,
        )


class AdaptiveInvestigationCoordinator:
    """Run a bounded causal investigation while preserving authority boundaries."""

    def __init__(
        self,
        *,
        round_source: AdaptiveRoundSource,
        reviser: AdaptiveHypothesisReviser,
        gateway: VerifiedObservationGateway,
        active_strategy_digest: str,
        selector: Selector = select_discriminating_observation,
        challenger_strategy_digest: str | None = None,
        challenger_selector: DiscriminationSelector | None = None,
        shadow_sink: AdaptiveShadowComparisonSink | None = None,
        iteration_sink: AdaptiveIterationSink | None = None,
        terminal_sink: AdaptiveTerminalSink | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._round_source = round_source
        self._reviser = reviser
        self._gateway = gateway
        self._active_strategy_digest = active_strategy_digest
        self._challenger_strategy_digest = challenger_strategy_digest
        self._challenger_selector = challenger_selector
        self._shadow_sink = shadow_sink
        self._selector = selector
        self._iteration_sink = iteration_sink
        self._terminal_sink = terminal_sink
        self._clock = clock or (lambda: datetime.now(UTC))
        if (challenger_strategy_digest is None) != (challenger_selector is None):
            raise ValueError("challenger strategy and selector MUST be supplied together")
        if shadow_sink is not None and challenger_selector is None:
            raise ValueError("shadow sink requires a challenger selector")

    async def investigate(
        self,
        *,
        session_id: str,
        initial_frame: HypothesisDiscriminationFrame,
        budget: AdaptiveInvestigationBudget,
        cancelled: asyncio.Event | None = None,
    ) -> AdaptiveInvestigationResult:
        """Run until Forseti closes the case or one pinned bound stops progress."""

        cancel_signal = cancelled or asyncio.Event()
        frame = initial_frame
        iterations: list[AdaptiveInvestigationIteration] = []
        used_queries = 0
        used_cost_units = 0
        disposition = AdaptiveInvestigationDisposition.HELD
        terminal_active_set_receipt_digest = frame.active_set_receipt_digest

        for round_index in range(1, budget.max_rounds + 1):
            stop = self._pre_round_stop(
                budget=budget,
                cancelled=cancel_signal,
                used_queries=used_queries,
            )
            if stop is not None:
                disposition = stop
                break
            try:
                async with asyncio.timeout(self._remaining_seconds(budget)):
                    proposal = await self._round_source.propose(frame)
            except TimeoutError:
                disposition = AdaptiveInvestigationDisposition.TIMED_OUT
                break
            if proposal.frame_digest != frame.frame_digest:
                raise ValueError("adaptive round source returned a substituted frame")
            stop = self._pre_round_stop(
                budget=budget,
                cancelled=cancel_signal,
                used_queries=used_queries,
            )
            if stop is not None:
                disposition = stop
                break
            try:
                async with asyncio.timeout(self._remaining_seconds(budget)):
                    selection, shadow_pending = await self._select(
                        frame,
                        proposal.candidates,
                    )
            except TimeoutError:
                disposition = AdaptiveInvestigationDisposition.TIMED_OUT
                break
            if selection is None:
                disposition = AdaptiveInvestigationDisposition.HELD
                break
            self._validate_active_selection(
                frame,
                proposal.candidates,
                selection,
            )
            stop = self._pre_round_stop(
                budget=budget,
                cancelled=cancel_signal,
                used_queries=used_queries,
            )
            if stop is not None:
                disposition = stop
                break
            if selection.selected_candidate_id is None:
                shadow_digest = await _await_shadow_digest(shadow_pending)
                iteration = build_adaptive_investigation_iteration(
                    round_index=round_index,
                    frame=frame,
                    selection=selection,
                    execution=None,
                    revision=None,
                    shadow_comparison_digest=shadow_digest,
                )
                await self._record_iteration(iteration)
                iterations.append(iteration)
                disposition = AdaptiveInvestigationDisposition.HELD
                break
            candidate = next(
                (
                    item
                    for item in proposal.candidates
                    if item.candidate_id == selection.selected_candidate_id
                ),
                None,
            )
            if candidate is None:
                raise ValueError("active selector returned an unknown observation candidate")
            binding = proposal.binding_for(candidate)
            if used_cost_units + binding.cost_units > budget.max_cost_units:
                disposition = AdaptiveInvestigationDisposition.COST_EXHAUSTED
                break
            used_queries += 1
            used_cost_units += binding.cost_units
            try:
                async with asyncio.timeout(self._remaining_seconds(budget)):
                    execution = await self._gateway.execute(
                        round_index=round_index,
                        frame=frame,
                        selection=selection,
                        candidate=candidate,
                        binding=binding,
                        cancelled=cancel_signal,
                    )
            except asyncio.CancelledError:
                if not cancel_signal.is_set():
                    raise
                execution = self._interrupted_execution(
                    round_index=round_index,
                    frame=frame,
                    selection=selection,
                    candidate=candidate,
                    binding=binding,
                    status="cancelled",
                    actual_cost_units=None,
                )
            except TimeoutError:
                execution = self._interrupted_execution(
                    round_index=round_index,
                    frame=frame,
                    selection=selection,
                    candidate=candidate,
                    binding=binding,
                    status="timed_out",
                    actual_cost_units=binding.cost_units,
                )
            consumed_cost = (
                execution.actual_cost_units
                if execution.actual_cost_units is not None
                else execution.reserved_cost_units
            )
            used_cost_units += consumed_cost - binding.cost_units
            shadow_digest = await _await_shadow_digest(shadow_pending)
            if execution.query_status == "timed_out":
                iteration = build_adaptive_investigation_iteration(
                    round_index=round_index,
                    frame=frame,
                    selection=selection,
                    execution=execution,
                    revision=None,
                    shadow_comparison_digest=shadow_digest,
                )
                await self._record_iteration(iteration)
                iterations.append(iteration)
                disposition = AdaptiveInvestigationDisposition.TIMED_OUT
                break
            post_query_stop = self._post_query_stop(
                budget=budget,
                cancelled=cancel_signal,
                execution=execution,
            )
            if post_query_stop is not None:
                iteration = build_adaptive_investigation_iteration(
                    round_index=round_index,
                    frame=frame,
                    selection=selection,
                    execution=execution,
                    revision=None,
                    shadow_comparison_digest=shadow_digest,
                )
                await self._record_iteration(iteration)
                iterations.append(iteration)
                disposition = post_query_stop
                break
            try:
                async with asyncio.timeout(self._remaining_seconds(budget)):
                    revision = await self._reviser.revise(
                        frame=frame,
                        execution=execution,
                    )
            except TimeoutError:
                iteration = build_adaptive_investigation_iteration(
                    round_index=round_index,
                    frame=frame,
                    selection=selection,
                    execution=execution,
                    revision=None,
                    shadow_comparison_digest=shadow_digest,
                )
                await self._record_iteration(iteration)
                iterations.append(iteration)
                disposition = AdaptiveInvestigationDisposition.TIMED_OUT
                break
            post_revision_stop = self._post_query_stop(
                budget=budget,
                cancelled=cancel_signal,
                execution=execution,
            )
            if post_revision_stop is not None:
                iteration = build_adaptive_investigation_iteration(
                    round_index=round_index,
                    frame=frame,
                    selection=selection,
                    execution=execution,
                    revision=None,
                    shadow_comparison_digest=shadow_digest,
                )
                await self._record_iteration(iteration)
                iterations.append(iteration)
                disposition = post_revision_stop
                break
            self._validate_revision(frame, execution, revision)
            iteration = build_adaptive_investigation_iteration(
                round_index=round_index,
                frame=frame,
                selection=selection,
                execution=execution,
                revision=revision,
                shadow_comparison_digest=shadow_digest,
            )
            await self._record_iteration(iteration)
            iterations.append(iteration)
            if revision.disposition.terminal:
                disposition = revision.disposition
                terminal_active_set_receipt_digest = revision.active_set_receipt_digest
                break
            frame = self._next_frame(frame, revision)
            terminal_active_set_receipt_digest = frame.active_set_receipt_digest
        else:
            disposition = AdaptiveInvestigationDisposition.ROUND_EXHAUSTED

        result = build_adaptive_investigation_result(
            session_id=session_id,
            incident_id=initial_frame.incident_id,
            workflow_version=_WORKFLOW_VERSION,
            active_strategy_digest=self._active_strategy_digest,
            challenger_strategy_digest=self._challenger_strategy_digest,
            budget=budget,
            iterations=tuple(iterations),
            disposition=disposition,
            terminal_frame_digest=frame.frame_digest,
            terminal_active_set_receipt_digest=terminal_active_set_receipt_digest,
            used_queries=used_queries,
            used_cost_units=used_cost_units,
        )
        if self._terminal_sink is not None:
            await self._terminal_sink.record(result)
        return result

    def _pre_round_stop(
        self,
        *,
        budget: AdaptiveInvestigationBudget,
        cancelled: asyncio.Event,
        used_queries: int,
    ) -> AdaptiveInvestigationDisposition | None:
        if cancelled.is_set():
            return AdaptiveInvestigationDisposition.CANCELLED
        if self._clock() >= budget.deadline_at:
            return AdaptiveInvestigationDisposition.TIMED_OUT
        if used_queries >= budget.max_queries:
            return AdaptiveInvestigationDisposition.QUERY_EXHAUSTED
        return None

    def _post_query_stop(
        self,
        *,
        budget: AdaptiveInvestigationBudget,
        cancelled: asyncio.Event,
        execution: AdaptiveObservationExecution,
    ) -> AdaptiveInvestigationDisposition | None:
        if cancelled.is_set():
            return AdaptiveInvestigationDisposition.CANCELLED
        if self._clock() >= budget.deadline_at:
            return AdaptiveInvestigationDisposition.TIMED_OUT
        if execution.query_status != "completed":
            return AdaptiveInvestigationDisposition.HELD
        return None

    @staticmethod
    def _validate_revision(
        frame: HypothesisDiscriminationFrame,
        execution: AdaptiveObservationExecution,
        revision: HypothesisRevisionSet,
    ) -> None:
        if revision.prior_active_set_receipt_digest != frame.active_set_receipt_digest:
            raise ValueError("hypothesis revision does not cite the prior active set")
        if revision.prior_frame_digest != frame.frame_digest:
            raise ValueError("hypothesis revision does not cite the prior frame")
        if revision.observation_result_digest != execution.result_digest:
            raise ValueError("hypothesis revision does not cite the selected observation")
        if revision.evidence_cutoff < frame.evidence_cutoff:
            raise ValueError("hypothesis revision evidence cutoff moved backward")

    @staticmethod
    def _next_frame(
        frame: HypothesisDiscriminationFrame,
        revision: HypothesisRevisionSet,
    ) -> HypothesisDiscriminationFrame:
        active_ids = revision.active_hypothesis_ids or frame.active_hypothesis_ids
        return build_hypothesis_discrimination_frame(
            incident_id=frame.incident_id,
            graph_revision=revision.graph_revision,
            evidence_cutoff=revision.evidence_cutoff,
            active_hypothesis_ids=active_ids,
            active_set_receipt_digest=revision.active_set_receipt_digest,
            cost_model_digest=frame.cost_model_digest,
        )

    async def _record_iteration(self, iteration: AdaptiveInvestigationIteration) -> None:
        if self._iteration_sink is not None:
            await self._iteration_sink.record(iteration)

    @staticmethod
    def _validate_active_selection(
        frame: HypothesisDiscriminationFrame,
        candidates: tuple[DiscriminatingObservationCandidate, ...],
        selection: HypothesisDiscriminationSelection,
    ) -> None:
        expected_digests = tuple(sorted(candidate.candidate_digest for candidate in candidates))
        if (
            selection.frame_digest != frame.frame_digest
            or selection.candidate_digests != expected_digests
        ):
            raise ValueError("active selection does not match the candidate frame")
        expected_total = (
            len(frame.active_hypothesis_ids) * (len(frame.active_hypothesis_ids) - 1) // 2
        )
        if selection.total_pair_count != expected_total:
            raise ValueError("active selection total pair count is invalid")
        if selection.selected_candidate_id is None:
            if selection.separated_pair_count != 0:
                raise ValueError("held active selection cannot separate pairs")
            return
        candidate = next(
            (item for item in candidates if item.candidate_id == selection.selected_candidate_id),
            None,
        )
        if candidate is None:
            raise ValueError("active selection names an unknown candidate")
        prediction_ids = tuple(item.hypothesis_id for item in candidate.predictions)
        if prediction_ids != frame.active_hypothesis_ids:
            raise ValueError("active selection candidate coverage is incomplete")
        outcomes = tuple(item.outcome for item in candidate.predictions)
        expected_separation = sum(
            outcomes[left] is not outcomes[right]
            for left in range(len(outcomes))
            for right in range(left + 1, len(outcomes))
        )
        if selection.separated_pair_count != expected_separation:
            raise ValueError("active selection pair separation is invalid")

    def _remaining_seconds(self, budget: AdaptiveInvestigationBudget) -> float:
        remaining = (budget.deadline_at - self._clock()).total_seconds()
        if remaining <= 0:
            raise TimeoutError("adaptive investigation deadline expired")
        return remaining

    @staticmethod
    def _interrupted_execution(
        *,
        round_index: int,
        frame: HypothesisDiscriminationFrame,
        selection: HypothesisDiscriminationSelection,
        candidate: DiscriminatingObservationCandidate,
        binding: VerifiedObservationPlanBinding,
        status: str,
        actual_cost_units: int | None,
    ) -> AdaptiveObservationExecution:
        result_digest = content_digest(
            {
                "plan_digest": binding.plan.plan_digest,
                "status": status,
                "execution_authority": False,
            }
        )
        return build_adaptive_observation_execution(
            round_index=round_index,
            frame_digest=frame.frame_digest,
            selection_digest=selection.selection_digest,
            candidate_digest=candidate.candidate_digest,
            binding_digest=binding.binding_digest,
            verification_receipt_digest=binding.verification_receipt_digest,
            plan_digest=binding.plan.plan_digest,
            result_digest=result_digest,
            query_status=status,
            evidence_refs=(),
            reserved_cost_units=binding.cost_units,
            actual_cost_units=actual_cost_units,
        )

    async def _select(
        self,
        frame: HypothesisDiscriminationFrame,
        candidates: tuple[DiscriminatingObservationCandidate, ...],
    ) -> tuple[
        HypothesisDiscriminationSelection | None,
        PendingShadowPersistence | None,
    ]:
        if self._challenger_selector is None:
            return self._selector(frame, candidates), None
        challenger_digest = self._challenger_strategy_digest
        if challenger_digest is None:  # pragma: no cover - constructor invariant
            raise RuntimeError("challenger selector lost its strategy digest")
        comparison = run_discrimination_shadow(
            frame=frame,
            candidates=candidates,
            active_strategy_digest=self._active_strategy_digest,
            challenger_strategy_digest=challenger_digest,
            active_selector=self._selector,
            challenger_selector=self._challenger_selector,
        )
        if self._shadow_sink is not None:
            task = asyncio.create_task(
                self._shadow_sink.record(comparison),
                name=f"adaptive-shadow-{comparison.comparison_id}",
            )
            task.add_done_callback(
                lambda completed: _observe_shadow_persistence(
                    completed,
                    frame_digest=frame.frame_digest,
                    comparison_digest=comparison.comparison_digest,
                )
            )
            return (
                comparison.active_recommendation,
                (comparison.comparison_digest, task),
            )
        return comparison.active_recommendation, None


def _observe_shadow_persistence(
    task: asyncio.Task[None],
    *,
    frame_digest: str,
    comparison_digest: str,
) -> None:
    if task.cancelled():
        _LOGGER.warning(
            "adaptive_shadow_comparison_persistence_cancelled",
            extra={
                "frame_digest": frame_digest,
                "comparison_digest": comparison_digest,
            },
        )
        return
    exception = task.exception()
    if exception is not None:
        _LOGGER.warning(
            "adaptive_shadow_comparison_persistence_failed",
            extra={
                "frame_digest": frame_digest,
                "comparison_digest": comparison_digest,
                "failure_type": type(exception).__name__,
            },
        )


async def _await_shadow_digest(
    pending: PendingShadowPersistence | None,
) -> str | None:
    if pending is None:
        return None
    digest, task = pending
    try:
        async with asyncio.timeout(0.05):
            await asyncio.shield(task)
    except TimeoutError:
        return None
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise
        return None
    except Exception:  # noqa: BLE001 - shadow persistence cannot block active work
        return None
    if task.cancelled() or task.exception() is not None:
        return None
    return digest


__all__ = [
    "AdaptiveHypothesisReviser",
    "AdaptiveInvestigationCoordinator",
    "AdaptiveIterationSink",
    "AdaptiveRoundProposal",
    "AdaptiveRoundSource",
    "AdaptiveShadowComparisonSink",
    "AdaptiveTerminalSink",
    "VerifiedObservationGateway",
]
