"""Tool-call adapter for governed chaos experiment execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

from fdai.core.chaos import (
    ExperimentOutcome,
    FaultInjectionHarness,
    FaultScenario,
)
from fdai.core.chaos.factory import ScenarioFactory
from fdai.core.chaos.injector import FaultInjector, SignalProbe
from fdai.core.chaos.scenario_catalog import CatalogEntry
from fdai.core.report_feed import signal_from_experiment
from fdai.core.report_feed.models import ReportSignal
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallReceipt,
    ToolCallRequest,
    ToolPreconditionError,
    ToolPromotionError,
)


class ReportSignalWriter(Protocol):
    async def record(self, signal: ReportSignal) -> None: ...


class GovernedChaosExecution(Protocol):
    async def execute(self, request: ToolCallRequest) -> ToolCallReceipt: ...


class ChaosExperimentToolExecutor:
    """Resolve a catalog scenario and run it through FaultInjectionHarness."""

    def __init__(
        self,
        *,
        entries: Sequence[CatalogEntry],
        promoted_ids: frozenset[str],
        factory: ScenarioFactory,
        context: Mapping[str, Any] | None = None,
        signal_writer: ReportSignalWriter | None = None,
        governed_execution: GovernedChaosExecution | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._entries = {entry.id: entry for entry in entries}
        self._promoted_ids = promoted_ids
        self._factory = factory
        self._context = dict(context or {})
        self._signal_writer = signal_writer
        self._governed_execution = governed_execution
        self._sleeper = sleeper

    async def execute(self, request: ToolCallRequest) -> ToolCallReceipt:
        scenario_id = _required_string(request.arguments, "scenario_id")
        targets = _required_targets(request.arguments)
        entry = self._entries.get(scenario_id)
        if entry is None:
            raise ToolPreconditionError(f"unknown chaos scenario {scenario_id!r}")
        scenario = _to_scenario(entry)

        injectors: Sequence[FaultInjector] = ()
        probe: SignalProbe | None = None
        if request.mode is Mode.ENFORCE:
            if "enforce" not in request.labels:
                raise ToolPromotionError("chaos enforce requires the enforce label")
            if scenario_id not in self._promoted_ids:
                raise ToolPromotionError(f"chaos scenario {scenario_id!r} is not promoted")
            if self._governed_execution is None:
                raise ToolPreconditionError(
                    "chaos enforce requires a governed impact and recovery executor"
                )
            return await self._governed_execution.execute(request)

        harness = FaultInjectionHarness(
            injectors=injectors,
            probe=probe,
            sleeper=self._sleeper,
        )
        result = await harness.run(scenario, approved_targets=targets, mode=request.mode)
        if self._signal_writer is not None:
            await self._signal_writer.record(signal_from_experiment(result))
        outcome, rollback = _tool_outcome(result.outcome, result.reverted)
        return ToolCallReceipt(
            outcome=outcome,
            receipt_ref=result.experiment_id,
            rollback_succeeded=rollback,
            detail=result.outcome.value,
        )


def _to_scenario(entry: CatalogEntry) -> FaultScenario:
    spec = entry.spec
    params = spec.get("params")
    return FaultScenario(
        scenario_id=entry.id,
        fault_type=str(spec["fault_family"]),
        description=str(spec["description"]),
        target_selector=str(spec["target_type"]),
        expected_signal=entry.expected_signal,
        blast_radius_cap=int(spec["blast_radius_cap"]),
        duration_seconds=float(spec["duration_seconds"]),
        params=(
            {str(key): str(value) for key, value in params.items()}
            if isinstance(params, Mapping)
            else {}
        ),
        rollback_note=str(spec.get("rollback_note") or ""),
    )


def _required_string(arguments: Mapping[str, object], field: str) -> str:
    value = arguments.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ToolPreconditionError(f"{field} MUST be a non-empty string")
    return value.strip()


def _required_targets(arguments: Mapping[str, object]) -> tuple[str, ...]:
    value = arguments.get("targets")
    if not isinstance(value, (list, tuple)) or not value:
        raise ToolPreconditionError("targets MUST be a non-empty array")
    targets = tuple(str(item).strip() for item in value)
    if any(not item for item in targets):
        raise ToolPreconditionError("targets MUST contain non-empty strings")
    return targets


def _tool_outcome(
    outcome: ExperimentOutcome, reverted: bool
) -> tuple[ToolCallOutcome, bool | None]:
    if outcome in {
        ExperimentOutcome.SHADOWED,
        ExperimentOutcome.VALIDATED,
        ExperimentOutcome.NOT_DETECTED,
    }:
        return ToolCallOutcome.SUCCEEDED, None
    if outcome is ExperimentOutcome.ROLLBACK_FAILED:
        return ToolCallOutcome.FAILED, False
    return ToolCallOutcome.STOPPED, reverted


__all__ = [
    "ChaosExperimentToolExecutor",
    "GovernedChaosExecution",
    "ReportSignalWriter",
]
