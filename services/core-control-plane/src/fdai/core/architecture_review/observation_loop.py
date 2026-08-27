"""Observation-mode ontology-grounded architecture review loop."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai.core.decision_case import build_decision_case
from fdai.core.decision_case.models import ActionOption, DecisionCase, ObjectiveEffect
from fdai.core.impact_analysis import (
    AffectedSet,
    ImpactEnvelopeRecord,
    ObjectiveBound,
    TelemetryRequirements,
    compile_impact_envelope,
)
from fdai.core.ontology_platform import (
    OntologyScenarioBranch,
    OntologyScenarioChangeSet,
    OntologyScenarioResult,
)
from fdai.core.operational_context import (
    OperationalContextSnapshot,
    OperationalEvidenceBundle,
)
from fdai.shared.contracts.models import OntologyLinkType, OntologyObjectType
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot


class ArchitectureReviewEvidenceUnavailableError(RuntimeError):
    """An authoritative ARB evidence dependency cannot answer."""


class ArchitectureReviewBackpressureError(RuntimeError):
    """An ARB evidence dependency is explicitly backpressured."""


@dataclass(frozen=True, slots=True)
class ArchitectureReviewEvidence:
    """Inputs returned by an authoritative evidence provider for one change."""

    bundle: OperationalEvidenceBundle
    base_graph: OntologyGraphSnapshot
    object_types: tuple[OntologyObjectType, ...]
    link_types: tuple[OntologyLinkType, ...]
    scenario_changes: OntologyScenarioChangeSet
    affected_set: AffectedSet
    objective_bounds: tuple[ObjectiveBound, ...] = ()
    required_signals: tuple[str, ...] = ("ontology_context",)
    forbidden_signals: tuple[str, ...] = ("mutation", "execution")
    telemetry_requirements: TelemetryRequirements = TelemetryRequirements(
        required_sources=("ontology",),
        freshness_seconds=300,
        cadence_seconds=60,
    )


class ArchitectureReviewContextSource(Protocol):
    """Resolve one authenticated current context for a normalized Change."""

    async def resolve(self, *, change: Mapping[str, object]) -> OperationalContextSnapshot: ...


class ArchitectureReviewEvidenceSource(Protocol):
    """Collect an immutable evidence bundle and bounded scenario inputs."""

    async def collect(
        self,
        *,
        change: Mapping[str, object],
        context: OperationalContextSnapshot,
    ) -> ArchitectureReviewEvidence: ...


class ArchitectureReviewStateStore(Protocol):
    """Persist completed observation results for duplicate and restart safety."""

    async def get(self, key: str) -> ArchitectureReviewObservation | None: ...

    async def put_if_absent(
        self,
        key: str,
        value: ArchitectureReviewObservation,
    ) -> ArchitectureReviewObservation | None: ...


class InMemoryArchitectureReviewStateStore:
    """Deterministic state store used by local and focused integration tests."""

    def __init__(self) -> None:
        self._values: dict[str, ArchitectureReviewObservation] = {}

    async def get(self, key: str) -> ArchitectureReviewObservation | None:
        return self._values.get(key)

    async def put_if_absent(
        self,
        key: str,
        value: ArchitectureReviewObservation,
    ) -> ArchitectureReviewObservation | None:
        existing = self._values.get(key)
        if existing is not None:
            return existing
        self._values[key] = value
        return None


@dataclass(frozen=True, slots=True)
class ArchitectureReviewObservation:
    """Replayable observation result with no approval, mutation, or execution authority."""

    change_id: str
    idempotency_key: str
    correlation_id: str
    target_ref: str
    recommendation: str
    reasons: tuple[str, ...]
    context: OperationalContextSnapshot | None
    evidence: ArchitectureReviewEvidence | None
    scenario: OntologyScenarioResult | None
    decision_case: DecisionCase | None
    impact_envelope: ImpactEnvelopeRecord | None
    mode: str = "observation"
    mutation_authority: bool = False
    execution_authority: bool = False
    replayed: bool = False

    @classmethod
    def hold(
        cls,
        *,
        change_id: str,
        idempotency_key: str,
        correlation_id: str,
        target_ref: str,
        reason: str,
    ) -> ArchitectureReviewObservation:
        """Create a safe hold when context or evidence cannot be obtained."""

        return cls(
            change_id=change_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            target_ref=target_ref,
            recommendation="hold",
            reasons=(reason,),
            context=None,
            evidence=None,
            scenario=None,
            decision_case=None,
            impact_envelope=None,
        )

    def to_mapping(self) -> dict[str, object]:
        """Return a bounded machine payload for the Forseti verdict topic."""

        return {
            "kind": "architecture_review",
            "change_id": self.change_id,
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
            "target_ref": self.target_ref,
            "recommendation": self.recommendation,
            "reasons": list(self.reasons),
            "mode": self.mode,
            "mutation_authority": self.mutation_authority,
            "execution_authority": self.execution_authority,
            "context_snapshot_id": self.context.snapshot_id if self.context else None,
            "evidence_bundle_digest": self.evidence.bundle.digest if self.evidence else None,
            "scenario_digest": self.scenario.scenario_digest if self.scenario else None,
            "decision_case_id": self.decision_case.case_id if self.decision_case else None,
            "impact_envelope_id": (
                self.impact_envelope.envelope_id if self.impact_envelope else None
            ),
            "decision_case": _decision_case_mapping(self.decision_case),
            "impact_envelope": _impact_mapping(self.impact_envelope),
        }


class OntologyArchitectureReviewLoop:
    """Compose one Change through authenticated context, evidence, scenario, and Forseti inputs."""

    def __init__(
        self,
        *,
        context_source: ArchitectureReviewContextSource,
        evidence_source: ArchitectureReviewEvidenceSource,
        state_store: ArchitectureReviewStateStore | None = None,
        deadline_seconds: float = 5.0,
        max_dependency_depth: int = 3,
        max_duration_seconds: int = 300,
        action_type_cap: int = 10,
        decision_cap: int = 10,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if deadline_seconds <= 0:
            raise ValueError("deadline_seconds MUST be positive")
        if not 1 <= max_dependency_depth <= 5:
            raise ValueError("max_dependency_depth MUST be in [1, 5]")
        if max_duration_seconds < 1 or action_type_cap < 1 or decision_cap < 1:
            raise ValueError("ARB bounds MUST be positive")
        self._context_source = context_source
        self._evidence_source = evidence_source
        self._state_store = state_store or InMemoryArchitectureReviewStateStore()
        self._deadline_seconds = deadline_seconds
        self._max_dependency_depth = max_dependency_depth
        self._max_duration_seconds = max_duration_seconds
        self._action_type_cap = action_type_cap
        self._decision_cap = decision_cap
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = asyncio.Lock()

    async def evaluate(
        self,
        change: Mapping[str, object],
    ) -> ArchitectureReviewObservation:
        """Evaluate a normalized Change once, suppressing duplicates by stable idempotency."""

        identity = _change_identity(change)
        async with self._lock:
            existing = await self._state_store.get(identity.idempotency_key)
            if existing is not None:
                if existing.change_id != identity.change_id:
                    raise ValueError("ARB idempotency key conflicts with another Change")
                return replace(existing, replayed=True)
            try:
                context = await asyncio.wait_for(
                    self._context_source.resolve(change=change),
                    timeout=self._deadline_seconds,
                )
                evidence = await asyncio.wait_for(
                    self._evidence_source.collect(change=change, context=context),
                    timeout=self._deadline_seconds,
                )
                observation = await asyncio.wait_for(
                    self._compose(identity, context, evidence),
                    timeout=self._deadline_seconds,
                )
            except (
                ArchitectureReviewBackpressureError,
                ArchitectureReviewEvidenceUnavailableError,
            ):
                observation = ArchitectureReviewObservation.hold(
                    **identity.to_kwargs(),
                    reason="evidence_unavailable",
                )
            except TimeoutError:
                observation = ArchitectureReviewObservation.hold(
                    **identity.to_kwargs(),
                    reason="deadline_exceeded",
                )
            except ValueError as exc:
                observation = ArchitectureReviewObservation.hold(
                    **identity.to_kwargs(),
                    reason=_safe_reason(exc),
                )
            existing = await self._state_store.put_if_absent(identity.idempotency_key, observation)
            return replace(existing, replayed=True) if existing is not None else observation

    async def replay(
        self,
        changes: Sequence[Mapping[str, object]],
    ) -> tuple[ArchitectureReviewObservation, ...]:
        """Replay changes in caller order without executing or mutating a target."""

        results: list[ArchitectureReviewObservation] = []
        for change in changes:
            results.append(await self.evaluate(change))
        return tuple(results)

    async def _compose(
        self,
        identity: _ChangeIdentity,
        context: OperationalContextSnapshot,
        evidence: ArchitectureReviewEvidence,
    ) -> ArchitectureReviewObservation:
        _validate_binding(identity, context, evidence.bundle)
        branch = OntologyScenarioBranch(
            branch_id=_branch_id(identity.change_id),
            evidence_bundle=evidence.bundle,
            base=evidence.base_graph,
            object_types=evidence.object_types,
            link_types=evidence.link_types,
        )
        scenario = await branch.materialize(evidence.scenario_changes)
        reasons = tuple(
            sorted(set((*context.conflicts, *context.stale_sources, *evidence.bundle.hold_reasons)))
        )
        objectives = context.objective_ids or ("arb-observation",)
        effects = tuple(
            ObjectiveEffect(
                objective_id=objective_id,
                utility=0.0,
                confidence=1.0 if not reasons else 0.0,
                metric="observation",
                expected_min=-1.0,
                expected_max=1.0,
                observation_window_seconds=self._max_duration_seconds,
            )
            for objective_id in objectives
        )
        option = ActionOption(
            option_id="observe-only",
            action_type=None,
            effects=effects,
            evidence_refs=(evidence.bundle.digest, scenario.scenario_digest),
        )
        case = build_decision_case(
            correlation_id=identity.correlation_id,
            context=context,
            created_at=context.recorded_at,
            no_action_effects=effects,
            options=(option,),
            protected_objective_ids=context.service_objective_ids + context.recovery_objective_ids,
            evidence_refs=(
                identity.change_id,
                evidence.bundle.digest,
                scenario.scenario_digest,
            ),
        )
        envelope = None
        if not reasons and evidence.affected_set.complete:
            envelope = compile_impact_envelope(
                decision_case_id=case.case_id,
                affected_set=evidence.affected_set,
                action_type_cap=self._action_type_cap,
                decision_cap=self._decision_cap,
                max_dependency_depth=self._max_dependency_depth,
                max_duration_seconds=self._max_duration_seconds,
                objective_bounds=evidence.objective_bounds
                or (ObjectiveBound(metric="observation", lower=0.0),),
                required_signals=evidence.required_signals,
                forbidden_signals=evidence.forbidden_signals,
                telemetry_requirements=evidence.telemetry_requirements,
                uncertainty=0.0,
                expires_at=context.cutoff + timedelta(seconds=self._max_duration_seconds),
            )
        else:
            reasons = tuple(sorted(set((*reasons, *evidence.affected_set.incomplete_reasons))))
        return ArchitectureReviewObservation(
            change_id=identity.change_id,
            idempotency_key=identity.idempotency_key,
            correlation_id=identity.correlation_id,
            target_ref=identity.target_ref,
            recommendation="conformant_observation" if envelope is not None else "hold",
            reasons=reasons,
            context=context,
            evidence=evidence,
            scenario=scenario,
            decision_case=case,
            impact_envelope=envelope,
        )


@dataclass(frozen=True, slots=True)
class _ChangeIdentity:
    change_id: str
    idempotency_key: str
    correlation_id: str
    target_ref: str

    def to_kwargs(self) -> dict[str, str]:
        return {
            "change_id": self.change_id,
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
            "target_ref": self.target_ref,
        }


def _change_identity(change: Mapping[str, object]) -> _ChangeIdentity:
    values = {
        name: str(change.get(name) or "").strip()
        for name in ("id", "idempotency_key", "correlation_id", "target_ref")
    }
    if not all(values.values()):
        raise ValueError(
            "ARB Change MUST include id, idempotency_key, correlation_id, and target_ref"
        )
    return _ChangeIdentity(
        change_id=values["id"],
        idempotency_key=values["idempotency_key"],
        correlation_id=values["correlation_id"],
        target_ref=values["target_ref"],
    )


def _validate_binding(
    identity: _ChangeIdentity,
    context: OperationalContextSnapshot,
    bundle: OperationalEvidenceBundle,
) -> None:
    if context.target_resource_id != identity.target_ref:
        raise ValueError("ARB context target does not match Change target")
    if bundle.cutoff != context.cutoff:
        raise ValueError("ARB evidence cutoff does not match authenticated context")
    if identity.target_ref not in bundle.scope:
        raise ValueError("ARB evidence scope does not contain Change target")


def _branch_id(change_id: str) -> str:
    value = "".join(char.lower() if char.isalnum() else "-" for char in change_id)
    value = value.strip("-") or "change"
    return f"arb-{value[:60]}"


def _safe_reason(error: ValueError) -> str:
    message = str(error)
    return message if message and len(message) <= 160 else "observation_review_invalid"


def _decision_case_mapping(case: DecisionCase | None) -> dict[str, object] | None:
    if case is None:
        return None
    return {
        "case_id": case.case_id,
        "correlation_id": case.correlation_id,
        "context_snapshot_id": case.context_snapshot_id,
        "evidence_refs": list(case.evidence_refs),
        "protected_objective_ids": list(case.protected_objective_ids),
        "active_constraint_ids": list(case.active_constraint_ids),
        "observation_only": True,
    }


def _impact_mapping(envelope: ImpactEnvelopeRecord | None) -> dict[str, object] | None:
    if envelope is None:
        return None
    return {
        "envelope_id": envelope.envelope_id,
        "decision_case_id": envelope.decision_case_id,
        "graph_revision": envelope.graph_revision,
        "target_set_digest": envelope.target_set_digest,
        "affected_set_digest": envelope.affected_set_digest,
        "max_affected_resources": envelope.max_affected_resources,
        "max_dependency_depth": envelope.max_dependency_depth,
        "max_duration_seconds": envelope.max_duration_seconds,
        "uncertainty": envelope.uncertainty,
        "expires_at": envelope.expires_at.isoformat(),
        "observation_only": True,
    }


__all__ = [
    "ArchitectureReviewBackpressureError",
    "ArchitectureReviewContextSource",
    "ArchitectureReviewEvidence",
    "ArchitectureReviewEvidenceSource",
    "ArchitectureReviewEvidenceUnavailableError",
    "ArchitectureReviewObservation",
    "ArchitectureReviewStateStore",
    "InMemoryArchitectureReviewStateStore",
    "OntologyArchitectureReviewLoop",
]
