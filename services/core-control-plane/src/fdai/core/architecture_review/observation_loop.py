"""Observation-mode ontology-grounded architecture review loop."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol, TypedDict

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


class ArchitectureReviewObservationSink(Protocol):
    """Persist an observation projection without granting action authority."""

    async def project_observation(
        self,
        observation: ArchitectureReviewObservation,
        *,
        process_id: str | None = None,
    ) -> None: ...


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
    change_digest: str
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
    observation_only: bool = True

    def __post_init__(self) -> None:
        if self.mode != "observation" or self.observation_only is not True:
            raise ValueError("ARB observations MUST remain observation-only")
        if self.mutation_authority or self.execution_authority:
            raise ValueError("ARB observations MUST NOT grant authority")

    @classmethod
    def hold(
        cls,
        *,
        change_id: str,
        idempotency_key: str,
        correlation_id: str,
        target_ref: str,
        change_digest: str,
        reason: str,
        observation_only: bool = True,
    ) -> ArchitectureReviewObservation:
        """Create a safe hold when context or evidence cannot be obtained."""

        return cls(
            change_id=change_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            target_ref=target_ref,
            change_digest=change_digest,
            recommendation="hold",
            reasons=(reason,),
            context=None,
            evidence=None,
            scenario=None,
            decision_case=None,
            impact_envelope=None,
            observation_only=observation_only,
        )

    def to_mapping(self) -> dict[str, object]:
        """Return a bounded machine payload for the Forseti verdict topic."""

        return {
            "kind": "architecture_review",
            "change_id": self.change_id,
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
            "target_ref": self.target_ref,
            "change_digest": self.change_digest,
            "recommendation": self.recommendation,
            "reasons": list(self.reasons),
            "mode": self.mode,
            "mutation_authority": self.mutation_authority,
            "execution_authority": self.execution_authority,
            "observation_only": self.observation_only,
            "context_snapshot_id": self.context.snapshot_id if self.context else None,
            "evidence_bundle_digest": self.evidence.bundle.digest if self.evidence else None,
            "scenario_digest": self.scenario.scenario_digest if self.scenario else None,
            "decision_case_id": self.decision_case.case_id if self.decision_case else None,
            "impact_envelope_id": (
                self.impact_envelope.envelope_id if self.impact_envelope else None
            ),
            "decision_case": _decision_case_mapping(self.decision_case),
            "impact_envelope": _impact_mapping(self.impact_envelope),
            "recorded_at": (
                self.context.recorded_at.isoformat() if self.context is not None else None
            ),
        }


class OntologyArchitectureReviewLoop:
    """Compose one Change through authenticated context, evidence, scenario, and Forseti inputs."""

    def __init__(
        self,
        *,
        context_source: ArchitectureReviewContextSource,
        evidence_source: ArchitectureReviewEvidenceSource,
        state_store: ArchitectureReviewStateStore | None = None,
        observation_sink: ArchitectureReviewObservationSink | None = None,
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
        self._observation_sink = observation_sink
        self._deadline_seconds = deadline_seconds
        self._max_dependency_depth = max_dependency_depth
        self._max_duration_seconds = max_duration_seconds
        self._action_type_cap = action_type_cap
        self._decision_cap = decision_cap
        self._clock = clock or (lambda: datetime.now(UTC))
        self._key_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()

    def bind_observation_sink(self, sink: ArchitectureReviewObservationSink | None) -> None:
        """Attach the production read-model sink before processing begins."""

        self._observation_sink = sink

    async def evaluate(
        self,
        change: Mapping[str, object],
    ) -> ArchitectureReviewObservation:
        """Evaluate a normalized Change once, suppressing duplicates by stable idempotency."""

        identity = _change_identity(change)
        async with self._lock_for_key(identity.idempotency_key):
            try:
                async with asyncio.timeout(self._deadline_seconds):
                    existing = await self._state_store.get(identity.idempotency_key)
                    if existing is not None:
                        if existing.change_digest != identity.change_digest:
                            raise ValueError(
                                "ARB idempotency key conflicts with another Change identity"
                            )
                        return replace(existing, replayed=True)
                    if change.get("intent_kind") != "planned":
                        observation = ArchitectureReviewObservation.hold(
                            **identity.to_kwargs(),
                            reason="unsupported_intent_kind",
                        )
                        stored = await self._state_store.put_if_absent(
                            identity.idempotency_key,
                            observation,
                        )
                        if stored is not None:
                            return replace(stored, replayed=True)
                        if self._observation_sink is not None:
                            await self._observation_sink.project_observation(
                                observation,
                                process_id=_process_id(change),
                            )
                        return observation
                    try:
                        context = await self._context_source.resolve(change=change)
                        evidence = await self._evidence_source.collect(
                            change=change,
                            context=context,
                        )
                        observation = await self._compose(identity, context, evidence)
                    except (
                        ArchitectureReviewBackpressureError,
                        ArchitectureReviewEvidenceUnavailableError,
                    ):
                        observation = ArchitectureReviewObservation.hold(
                            **identity.to_kwargs(),
                            reason="evidence_unavailable",
                        )
                    except ValueError as exc:
                        observation = ArchitectureReviewObservation.hold(
                            **identity.to_kwargs(),
                            reason=_safe_reason(exc),
                        )
                    existing = await self._state_store.put_if_absent(
                        identity.idempotency_key,
                        observation,
                    )
                    if existing is not None:
                        if existing.change_digest != identity.change_digest:
                            raise ValueError(
                                "ARB idempotency key conflicts with another Change identity"
                            )
                        return replace(existing, replayed=True)
                    if self._observation_sink is not None:
                        await self._observation_sink.project_observation(
                            observation,
                            process_id=_process_id(change),
                        )
                    return observation
            except TimeoutError:
                observation = ArchitectureReviewObservation.hold(
                    **identity.to_kwargs(),
                    reason="deadline_exceeded",
                )
                existing = await self._state_store.put_if_absent(
                    identity.idempotency_key,
                    observation,
                )
                if existing is not None:
                    return replace(existing, replayed=True)
                if self._observation_sink is not None:
                    await self._observation_sink.project_observation(
                        observation,
                        process_id=_process_id(change),
                    )
                return observation

    async def replay(
        self,
        changes: Sequence[Mapping[str, object]],
    ) -> tuple[ArchitectureReviewObservation, ...]:
        """Replay changes in caller order without executing or mutating a target."""

        results: list[ArchitectureReviewObservation] = []
        for change in changes:
            results.append(await self.evaluate(change))
        return tuple(results)

    def _lock_for_key(self, key: str) -> asyncio.Lock:
        lock = self._key_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._key_locks[key] = lock
        self._key_locks.move_to_end(key)
        return lock

    async def _compose(
        self,
        identity: _ChangeIdentity,
        context: OperationalContextSnapshot,
        evidence: ArchitectureReviewEvidence,
    ) -> ArchitectureReviewObservation:
        _validate_binding(identity, context, evidence.bundle)
        branch = OntologyScenarioBranch(
            branch_id=_branch_id(identity.change_id, identity.change_digest),
            evidence_bundle=evidence.bundle,
            base=evidence.base_graph,
            object_types=evidence.object_types,
            link_types=evidence.link_types,
        )
        scenario = await branch.materialize(evidence.scenario_changes)
        reasons = tuple(
            sorted(set((*context.conflicts, *context.stale_sources, *evidence.bundle.hold_reasons)))
        )
        if not context.objective_ids:
            return ArchitectureReviewObservation(
                **identity.to_kwargs(),
                recommendation="hold",
                reasons=tuple(sorted(set((*reasons, "objectives_missing")))),
                context=context,
                evidence=evidence,
                scenario=scenario,
                decision_case=None,
                impact_envelope=None,
            )
        objectives = context.objective_ids
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
            change_digest=identity.change_digest,
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
    change_digest: str

    def to_kwargs(self) -> _IdentityKwargs:
        return {
            "change_id": self.change_id,
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
            "target_ref": self.target_ref,
            "change_digest": self.change_digest,
        }


class _IdentityKwargs(TypedDict):
    change_id: str
    idempotency_key: str
    correlation_id: str
    target_ref: str
    change_digest: str


def _change_identity(change: Mapping[str, object]) -> _ChangeIdentity:
    values = {
        name: str(change.get(name) or "").strip()
        for name in ("id", "idempotency_key", "correlation_id", "target_ref")
    }
    if not all(values.values()):
        raise ValueError(
            "ARB Change MUST include id, idempotency_key, correlation_id, and target_ref"
        )
    change_digest = _digest_mapping(change)
    return _ChangeIdentity(
        change_id=values["id"],
        idempotency_key=values["idempotency_key"],
        correlation_id=values["correlation_id"],
        target_ref=values["target_ref"],
        change_digest=change_digest,
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
    if tuple(sorted(set(bundle.scope))) != (identity.target_ref,):
        raise ValueError("ARB evidence scope does not exactly match Change target")
    releases = tuple(context.catalog_versions)
    if _release_value(releases, "ontology") != bundle.ontology_release_digest:
        raise ValueError("ARB evidence ontology release does not match authenticated context")
    if _release_value(releases, "catalog") != bundle.catalog_revision:
        raise ValueError("ARB evidence catalog release does not match authenticated context")


def _branch_id(change_id: str, change_digest: str) -> str:
    value = "".join(char.lower() if char.isalnum() else "-" for char in change_id)
    value = value.strip("-") or "change"
    return f"arb-{value[:40]}-{change_digest[:24]}"


def _digest_mapping(change: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(_canonical_value(change), separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _canonical_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _process_id(change: Mapping[str, object]) -> str | None:
    value = change.get("process_id")
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _release_value(releases: tuple[tuple[str, str], ...], name: str) -> str:
    values = tuple(value for key, value in releases if key == name)
    if len(values) != 1 or not values[0].strip():
        raise ValueError(f"ARB context MUST contain exactly one {name} release")
    return values[0]


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
    "ArchitectureReviewObservationSink",
    "ArchitectureReviewStateStore",
    "InMemoryArchitectureReviewStateStore",
    "OntologyArchitectureReviewLoop",
]
