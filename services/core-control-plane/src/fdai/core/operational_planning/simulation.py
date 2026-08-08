"""Planning simulation through the reviewed programmatic pipeline sandbox."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.core.decision_case import ObjectiveEffect
from fdai.core.operational_context import OperationalContextSnapshot
from fdai.core.programmatic_pipeline.models import (
    ProgrammaticPipelineLimits,
    ProgrammaticPipelineStatus,
    ProgrammaticToolPipelineRequest,
    ProgrammaticToolPipelineResult,
)
from fdai.shared.contracts.models import OntologyDeclarationKind, OntologyTypeRef

from .models import SimulationReceipt, SimulationStatus

_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ProgrammaticPlanningRunner(Protocol):
    async def run(
        self,
        request: ProgrammaticToolPipelineRequest,
    ) -> ProgrammaticToolPipelineResult: ...


@dataclass(frozen=True, slots=True)
class PlanningProgram:
    function_ref: OntologyTypeRef
    reviewed_source: str
    source_digest: str
    sandbox_profile_id: str
    allowed_read_tools: frozenset[str]
    limits: ProgrammaticPipelineLimits = ProgrammaticPipelineLimits()

    def __post_init__(self) -> None:
        if self.function_ref.kind is not OntologyDeclarationKind.FUNCTION:
            raise ValueError("planning program function_ref MUST reference a function")
        if len(self.source_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.source_digest
        ):
            raise ValueError("planning program source_digest MUST be SHA-256")
        actual = hashlib.sha256(self.reviewed_source.encode("utf-8")).hexdigest()
        if actual != self.source_digest:
            raise ValueError("planning program source digest mismatch")
        if not self.allowed_read_tools:
            raise ValueError("planning program requires bounded read tools")


class ProgrammaticPlanningSimulator:
    """Execute one exact logic artifact without mutation or executor identity."""

    def __init__(
        self,
        *,
        runner: ProgrammaticPlanningRunner,
        program: PlanningProgram,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._runner = runner
        self._program = program
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def simulate(
        self,
        *,
        context: OperationalContextSnapshot,
        candidate_id: str,
        action_type: str | None,
        effects: tuple[ObjectiveEffect, ...],
        observed_at: datetime,
    ) -> SimulationReceipt:
        input_payload = {
            "candidate_id": candidate_id,
            "action_type": action_type,
            "context_snapshot_id": context.snapshot_id,
            "observed_at": observed_at.isoformat(),
            "effects": [_effect_mapping(effect) for effect in effects],
        }
        input_json = json.dumps(
            input_payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        identity = hashlib.sha256(
            f"{self._program.function_ref.model_dump_json()}:{input_json}".encode()
        ).hexdigest()
        run_id = f"planning-simulation:{identity}"
        request = ProgrammaticToolPipelineRequest(
            run_id=run_id,
            reviewed_source=self._program.reviewed_source,
            reviewed_source_digest=self._program.source_digest,
            idempotency_key=run_id,
            input_json=(input_json,),
            allowed_read_tools=self._program.allowed_read_tools,
            sandbox_profile_id=self._program.sandbox_profile_id,
            limits=self._program.limits,
        )
        started_at = self._clock()
        result = await self._runner.run(request)
        completed_at = self._clock()
        status = _simulation_status(result.status)
        predicted_effects: tuple[ObjectiveEffect, ...] = ()
        requires_review = status is not SimulationStatus.SUCCEEDED
        reason = result.detail or result.status.value
        if status is SimulationStatus.SUCCEEDED:
            try:
                decoded = _decode_output(result.final_json)
                predicted_effects = decoded.effects
                requires_review = decoded.requires_review
                reason = decoded.reason_code
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                status = SimulationStatus.UNSCORABLE
                requires_review = True
                reason = f"invalid_simulation_output:{type(exc).__name__}"
        evidence_refs = tuple(
            dict.fromkeys(
                (
                    *result.receipt_refs,
                    f"programmatic-pipeline:{run_id}:{result.source_digest}",
                )
            )
        )
        return SimulationReceipt(
            receipt_id=f"simulation:{identity}",
            candidate_id=candidate_id,
            snapshot_id=context.snapshot_id,
            logic_invocation_id=f"logic-invocation:{identity}",
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            evidence_refs=evidence_refs,
            predicted_effects=predicted_effects,
            requires_review=requires_review,
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class _DecodedOutput:
    effects: tuple[ObjectiveEffect, ...]
    requires_review: bool
    reason_code: str


def _decode_output(raw: str | None) -> _DecodedOutput:
    if raw is None:
        raise ValueError("simulation output is missing")
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {
        "effects",
        "reason_code",
        "requires_review",
    }:
        raise ValueError("simulation output has an unexpected shape")
    if not isinstance(value["requires_review"], bool):
        raise TypeError("simulation requires_review MUST be boolean")
    reason_code = value["reason_code"]
    if not isinstance(reason_code, str) or _REASON_CODE.fullmatch(reason_code) is None:
        raise ValueError("simulation reason_code MUST be canonical")
    raw_effects = value["effects"]
    if not isinstance(raw_effects, list) or not 1 <= len(raw_effects) <= 32:
        raise ValueError("simulation effects MUST be a bounded list")
    effects = tuple(_decode_effect(item) for item in raw_effects)
    if len({effect.objective_id for effect in effects}) != len(effects):
        raise ValueError("simulation effects MUST have unique objective ids")
    return _DecodedOutput(effects, value["requires_review"], reason_code)


def _decode_effect(value: Any) -> ObjectiveEffect:
    if not isinstance(value, dict) or set(value) != {
        "confidence",
        "expected_max",
        "expected_min",
        "metric",
        "objective_id",
        "observation_window_seconds",
        "utility",
    }:
        raise ValueError("simulation effect has an unexpected shape")
    return ObjectiveEffect(
        objective_id=value["objective_id"],
        utility=value["utility"],
        confidence=value["confidence"],
        metric=value["metric"],
        expected_min=value["expected_min"],
        expected_max=value["expected_max"],
        observation_window_seconds=value["observation_window_seconds"],
    )


def _effect_mapping(effect: ObjectiveEffect) -> dict[str, object]:
    return {
        "objective_id": effect.objective_id,
        "utility": effect.utility,
        "confidence": effect.confidence,
        "metric": effect.metric,
        "expected_min": effect.expected_min,
        "expected_max": effect.expected_max,
        "observation_window_seconds": effect.observation_window_seconds,
    }


def _simulation_status(status: ProgrammaticPipelineStatus) -> SimulationStatus:
    if status is ProgrammaticPipelineStatus.SUCCEEDED:
        return SimulationStatus.SUCCEEDED
    if status is ProgrammaticPipelineStatus.TIMED_OUT:
        return SimulationStatus.TIMED_OUT
    if status in {ProgrammaticPipelineStatus.FAILED, ProgrammaticPipelineStatus.REJECTED}:
        return SimulationStatus.FAILED
    return SimulationStatus.UNSCORABLE


__all__ = [
    "PlanningProgram",
    "ProgrammaticPlanningRunner",
    "ProgrammaticPlanningSimulator",
]
