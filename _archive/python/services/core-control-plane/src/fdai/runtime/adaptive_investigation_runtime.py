"""Runtime composition for one bounded adaptive causal investigation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.rca.discrimination import (
    HypothesisDiscriminationFrame,
    select_discriminating_observation,
)
from fdai.core.rca.discrimination_shadow import DiscriminationSelector
from fdai.core.read_investigation.adaptive import (
    AdaptiveHypothesisReviser,
    AdaptiveInvestigationCoordinator,
    AdaptiveRoundSource,
    AdaptiveShadowComparisonSink,
    Selector,
    VerifiedObservationGateway,
)
from fdai.core.read_investigation.adaptive_contract import (
    AdaptiveInvestigationBudget,
    AdaptiveInvestigationDisposition,
    AdaptiveInvestigationResult,
)
from fdai.core.read_investigation.adaptive_process import (
    AdaptiveInvestigationProcessRecorder,
)
from fdai.shared.contracts.models import OntologyTypeRef
from fdai.shared.providers.process_runtime import ProcessRuntimeStore

if TYPE_CHECKING:
    from fdai.core.operational_planning.investigation_handoff import (
        InvestigationPlanningHandoff,
    )


class InvestigationPlanningHandoffSink(Protocol):
    """Idempotently publish one proposal-only handoff by its stable handoff id."""

    async def publish(self, handoff: InvestigationPlanningHandoff) -> None: ...


class AdaptiveInvestigationRuntime:
    """Create the Process recorder and run one authority-free adaptive session."""

    def __init__(
        self,
        *,
        process_store: ProcessRuntimeStore,
        round_source: AdaptiveRoundSource,
        reviser: AdaptiveHypothesisReviser,
        gateway: VerifiedObservationGateway,
        active_strategy_digest: str,
        selector: Selector = select_discriminating_observation,
        challenger_strategy_digest: str | None = None,
        challenger_selector: DiscriminationSelector | None = None,
        shadow_sink: AdaptiveShadowComparisonSink | None = None,
        planning_handoff_sink: InvestigationPlanningHandoffSink | None = None,
        planning_action_type_refs: tuple[OntologyTypeRef, ...] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._process_store = process_store
        self._round_source = round_source
        self._reviser = reviser
        self._gateway = gateway
        self._active_strategy_digest = active_strategy_digest
        self._selector = selector
        self._challenger_strategy_digest = challenger_strategy_digest
        self._challenger_selector = challenger_selector
        self._shadow_sink = shadow_sink
        self._planning_handoff_sink = planning_handoff_sink
        self._planning_action_type_refs = planning_action_type_refs
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run(
        self,
        *,
        session_id: str,
        target_resource_id: str,
        correlation_id: str,
        initial_frame: HypothesisDiscriminationFrame,
        budget: AdaptiveInvestigationBudget,
        cancelled: asyncio.Event | None = None,
    ) -> AdaptiveInvestigationResult:
        """Persist Process creation before running and terminal closure afterward."""

        recorder = AdaptiveInvestigationProcessRecorder(
            store=self._process_store,
            session_id=session_id,
            incident_id=initial_frame.incident_id,
            target_resource_id=target_resource_id,
            correlation_id=correlation_id,
            initial_frame=initial_frame,
            active_strategy_digest=self._active_strategy_digest,
            challenger_strategy_digest=self._challenger_strategy_digest,
            budget=budget,
            planning_handoff_config_digest=content_digest(
                {
                    "enabled": self._planning_handoff_sink is not None,
                    "action_type_refs": [
                        item.model_dump(mode="json") for item in self._planning_action_type_refs
                    ],
                }
            ),
            clock=self._clock,
        )
        coordinator = AdaptiveInvestigationCoordinator(
            round_source=self._round_source,
            reviser=self._reviser,
            gateway=self._gateway,
            active_strategy_digest=self._active_strategy_digest,
            selector=self._selector,
            challenger_strategy_digest=self._challenger_strategy_digest,
            challenger_selector=self._challenger_selector,
            shadow_sink=self._shadow_sink,
            iteration_sink=recorder,
            terminal_sink=recorder,
            clock=self._clock,
        )
        try:
            process_start = await recorder.start()
        except asyncio.CancelledError:
            snapshot = await asyncio.shield(self._process_store.get(session_id))
            if snapshot is not None and snapshot.status.value == "running":
                await asyncio.shield(recorder.record_cancellation("startup_task_cancelled"))
            raise
        if process_start.replayed:
            if not process_start.snapshot.status.terminal:
                raise RuntimeError("adaptive investigation running replay requires explicit resume")
            if process_start.snapshot.status.value == "failed":
                raise RuntimeError("adaptive investigation previous attempt failed")
            try:
                replayed = await recorder.replay_terminal_result()
            except ValueError as exc:
                raise RuntimeError("adaptive investigation terminal result is unavailable") from exc
            await self._publish_planning_handoff(
                replayed,
                recorder=recorder,
                correlation_id=correlation_id,
                target_resource_id=target_resource_id,
            )
            return replayed
        try:
            result = await coordinator.investigate(
                session_id=session_id,
                initial_frame=initial_frame,
                budget=budget,
                cancelled=cancelled,
            )
        except asyncio.CancelledError:
            await recorder.record_cancellation("runtime_task_cancelled")
            raise
        except Exception as exc:
            await recorder.record_failure(type(exc).__name__)
            raise
        await self._publish_planning_handoff(
            result,
            recorder=recorder,
            correlation_id=correlation_id,
            target_resource_id=target_resource_id,
        )
        return result

    async def _publish_planning_handoff(
        self,
        result: AdaptiveInvestigationResult,
        *,
        recorder: AdaptiveInvestigationProcessRecorder,
        correlation_id: str,
        target_resource_id: str,
    ) -> None:
        if (
            self._planning_handoff_sink is not None
            and result.disposition is AdaptiveInvestigationDisposition.CONVERGED
        ):
            from fdai.core.operational_planning.investigation_handoff import (
                planning_handoff_from_adaptive_result,
            )

            handoff = planning_handoff_from_adaptive_result(
                result,
                correlation_id=correlation_id,
                target_resource_ref=target_resource_id,
                action_type_refs=self._planning_action_type_refs,
            )
            if await recorder.planning_handoff_was_published(handoff.handoff_id):
                return
            await self._planning_handoff_sink.publish(handoff)
            await recorder.record_planning_handoff_published(handoff.handoff_id)


__all__ = ["AdaptiveInvestigationRuntime", "InvestigationPlanningHandoffSink"]
