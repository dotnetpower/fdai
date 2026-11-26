"""Off-path adversarial chaos scenario generation contract for Loki."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from fdai.agents._framework.loki_scheduling import ChaosScheduleConfig, validate_config
from fdai.agents._framework.topics import stable_idempotency_key

MAX_GENERATED_SCENARIOS = 8
MAX_SCENARIO_FIELD_CHARS = 512


@dataclass(frozen=True, slots=True)
class ChaosScenarioCandidate:
    """One inert generated scenario candidate."""

    scenario_id: str
    schedule: ChaosScheduleConfig
    evidence_refs: tuple[str, ...]


class ChaosScenarioGenerator(Protocol):
    """Off-path generator port. No Loki hot path binds or calls this by default."""

    async def generate_scenarios(self, design_ref: str) -> Sequence[ChaosScenarioCandidate]: ...


def frozen_corpus_key(schedule: ChaosScheduleConfig) -> str:
    """Return the regression-corpus identity for a scenario's coverage shape."""

    return stable_idempotency_key(
        "loki-adversarial-corpus",
        schedule.action_type,
        schedule.targets,
        schedule.causal_hypothesis_ref,
        schedule.refutation_query_ref,
        schedule.impact_envelope_id,
        schedule.recovery_plan_id,
    )


def validate_candidate(
    candidate: ChaosScenarioCandidate,
    *,
    frozen_corpus: Mapping[str, ChaosScheduleConfig],
) -> str:
    """Return ``accepted`` or a stable rejection reason for one candidate."""

    if _bounded_string(candidate.scenario_id) is None:
        return "invalid_identity"
    if len(candidate.evidence_refs) < 1 or any(
        _bounded_string(ref) is None for ref in candidate.evidence_refs
    ):
        return "missing_evidence"
    schedule_reason = validate_config(candidate.schedule)
    if schedule_reason:
        return schedule_reason
    if frozen_corpus_key(candidate.schedule) in frozen_corpus:
        return "duplicate_coverage"
    if _weakens_existing(candidate.schedule, frozen_corpus.values()):
        return "weakened_coverage"
    return "accepted"


def audit_payload(
    candidate: ChaosScenarioCandidate,
    *,
    design_ref: str,
    result: str,
) -> dict[str, Any]:
    """Build Loki-owned inert audit evidence for a generated candidate."""

    return {
        "kind": "adversarial_scenario_candidate",
        "scenario_state": result,
        "inert": True,
        "execution_authority": False,
        "human_approval_required": True,
        "correlation_id": stable_idempotency_key(
            "loki-adversarial-scenario-correlation",
            design_ref,
            candidate.scenario_id,
        ),
        "idempotency_key": stable_idempotency_key(
            "loki-adversarial-scenario-audit",
            design_ref,
            candidate.scenario_id,
            result,
        ),
        "scenario_id": candidate.scenario_id,
        "schedule_id": candidate.schedule.schedule_id,
        "action_type": candidate.schedule.action_type,
        "targets": list(candidate.schedule.targets),
        "evidence_refs": list(candidate.evidence_refs),
    }


def _weakens_existing(
    schedule: ChaosScheduleConfig,
    existing: Iterable[ChaosScheduleConfig],
) -> bool:
    targets = set(schedule.targets)
    for item in existing:
        if schedule.action_type != item.action_type:
            continue
        existing_targets = set(item.targets)
        if targets < existing_targets:
            return True
    return False


def _bounded_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_SCENARIO_FIELD_CHARS
        or any((ord(char) < 32 and char not in "\t") or ord(char) == 127 for char in normalized)
    ):
        return None
    return normalized


__all__ = [
    "MAX_GENERATED_SCENARIOS",
    "ChaosScenarioCandidate",
    "ChaosScenarioGenerator",
    "audit_payload",
    "frozen_corpus_key",
    "validate_candidate",
]
