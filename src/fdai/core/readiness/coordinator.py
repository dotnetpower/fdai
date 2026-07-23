"""Bounded phased coordinator for deterministic startup readiness."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from fdai.core.readiness.models import (
    AuthorityCeiling,
    EvidenceRequirement,
    ProbeStatus,
    StartupPhase,
    StartupProbeResult,
    StartupProbeSpec,
    StartupReadinessReport,
)
from fdai.core.readiness.reducer import reduce_startup_readiness
from fdai.core.readiness.report import (
    HandoffVerdict,
    ReadinessFinding,
    ReadinessReport,
)
from fdai.core.readiness.signal import OwnershipTransfer
from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode
from fdai.shared.contracts.validation import EventValidator
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.feasibility_probe import FindingSeverity, ProbeFinding
from fdai.shared.providers.projection import Finding, Severity
from fdai.shared.providers.startup_probe import StartupProbe, StartupProbeRequest
from fdai.shared.providers.state_store import StateStore

_LATEST_REPORT_KEY = "runtime:startup-readiness:latest"
_TRANSITION_TOPIC = "runtime.readiness.transitions"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class StartupProbeBudget:
    """Global limits for one complete startup probe pass."""

    max_concurrency: int = 4
    per_probe_timeout_seconds: float = 10.0
    phase_timeout_seconds: float = 30.0
    retries: int = 1
    total_cost_limit_usd: float = 0.05
    model_sample_count: int = 2

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("startup max_concurrency MUST be >= 1")
        if self.per_probe_timeout_seconds <= 0 or self.phase_timeout_seconds <= 0:
            raise ValueError("startup probe deadlines MUST be > 0")
        if self.retries < 0:
            raise ValueError("startup probe retries MUST be >= 0")
        if self.total_cost_limit_usd < 0:
            raise ValueError("startup cost limit MUST be >= 0")
        if self.model_sample_count < 2:
            raise ValueError("startup model probes require at least two samples")


class StartupReadinessCoordinator:
    """Run configured probes before event processing and persist the result."""

    def __init__(
        self,
        *,
        specs: Sequence[StartupProbeSpec],
        probes: Sequence[StartupProbe[StartupProbeResult]],
        state_store: StateStore,
        event_bus: EventBus,
        event_validator: EventValidator,
        deployment_ceilings: Mapping[str, AuthorityCeiling] | None = None,
        budget: StartupProbeBudget | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._specs = tuple(specs)
        self._probes = {probe.probe_id: probe for probe in probes}
        if len(self._probes) != len(probes):
            raise ValueError("startup probe implementations MUST be unique by probe id")
        self._state_store = state_store
        self._event_bus = event_bus
        self._event_validator = event_validator
        self._deployment_ceilings = dict(deployment_ceilings or {})
        self._budget = budget or StartupProbeBudget()
        self._clock = clock

    async def evaluate(self) -> StartupReadinessReport:
        """Execute all four phases, persist latest evidence, and publish transitions."""
        previous = await self._state_store.read_state(_LATEST_REPORT_KEY)
        results: list[StartupProbeResult] = []
        remaining_cost = self._budget.total_cost_limit_usd
        for phase in StartupPhase:
            phase_specs = tuple(spec for spec in self._specs if spec.phase is phase)
            phase_results, spent = await self._run_phase(phase_specs, remaining_cost)
            results.extend(phase_results)
            remaining_cost = max(0.0, remaining_cost - spent)

        generated_at = self._clock()
        report = reduce_startup_readiness(
            self._specs,
            results,
            generated_at=generated_at,
            deployment_ceilings=self._deployment_ceilings,
        )
        serialized = report.to_dict()
        await self._state_store.write_state(_LATEST_REPORT_KEY, serialized)
        previous_decision = str(previous.get("decision")) if previous is not None else None
        if previous_decision != report.decision.value:
            await self._publish_transition(previous_decision, report)
        return report

    async def _run_phase(
        self,
        specs: Sequence[StartupProbeSpec],
        remaining_cost: float,
    ) -> tuple[list[StartupProbeResult], float]:
        semaphore = asyncio.Semaphore(self._budget.max_concurrency)
        runnable: list[StartupProbeSpec] = []
        immediate: list[StartupProbeResult] = []
        reserved_cost = 0.0
        for spec in sorted(specs, key=lambda item: item.probe_id):
            if spec.probe_id not in self._probes:
                continue
            if reserved_cost + spec.estimated_cost_usd > remaining_cost:
                immediate.append(self._failure(spec, ProbeStatus.FAILED, "cost_budget_exhausted"))
                continue
            reserved_cost += spec.estimated_cost_usd
            runnable.append(spec)

        async def execute(spec: StartupProbeSpec) -> StartupProbeResult:
            probe = self._probes[spec.probe_id]
            async with semaphore:
                return await self._run_probe(spec, probe)

        try:
            async with asyncio.timeout(self._budget.phase_timeout_seconds):
                completed = await asyncio.gather(*(execute(spec) for spec in runnable))
                return [*immediate, *completed], reserved_cost
        except TimeoutError:
            return [
                self._failure(spec, ProbeStatus.TIMED_OUT, "phase_deadline_exceeded")
                for spec in runnable
            ] + immediate, reserved_cost

    async def _run_probe(
        self,
        spec: StartupProbeSpec,
        probe: StartupProbe[StartupProbeResult],
    ) -> StartupProbeResult:
        for attempt in range(self._budget.retries + 1):
            request = StartupProbeRequest(
                deadline=self._clock() + timedelta(seconds=self._budget.per_probe_timeout_seconds),
                cost_limit_usd=spec.estimated_cost_usd,
                model_sample_count=self._budget.model_sample_count,
                synthetic_scope=spec.synthetic_scope,
            )
            try:
                result = await asyncio.wait_for(
                    probe.run(request),
                    timeout=self._budget.per_probe_timeout_seconds,
                )
                if result.probe_id != spec.probe_id:
                    return self._failure(spec, ProbeStatus.CRASHED, "probe_id_mismatch")
                return self._validate_capability_evidence(spec, result)
            except TimeoutError:
                if attempt == self._budget.retries:
                    return self._failure(spec, ProbeStatus.TIMED_OUT, "probe_deadline_exceeded")
            except Exception:  # noqa: BLE001 - provider details must not cross this boundary
                if attempt == self._budget.retries:
                    return self._failure(spec, ProbeStatus.CRASHED, "probe_crashed")
        raise AssertionError("startup retry loop exhausted without a terminal result")

    def _validate_capability_evidence(
        self,
        spec: StartupProbeSpec,
        result: StartupProbeResult,
    ) -> StartupProbeResult:
        requirement = spec.evidence_requirement
        if requirement is EvidenceRequirement.STANDARD or result.status is not ProbeStatus.PASSED:
            return result
        evidence = result.model_evidence
        if evidence is None:
            return self._failure(spec, ProbeStatus.FAILED, "model_evidence_missing")
        proven = {
            EvidenceRequirement.MODEL_STREAM: bool(evidence.ttft_ms and evidence.output_token_rate),
            EvidenceRequirement.MODEL_EMBEDDING: evidence.embedding_dimensions is not None,
            EvidenceRequirement.MODEL_STRUCTURED_OUTPUT: evidence.structured_output_proven,
            EvidenceRequirement.MODEL_TOOL_CALLING: evidence.tool_calling_proven,
        }[requirement]
        return result if proven else self._failure(spec, ProbeStatus.FAILED, "capability_unproven")

    def _failure(
        self,
        spec: StartupProbeSpec,
        status: ProbeStatus,
        failure_class: str,
    ) -> StartupProbeResult:
        observed_at = self._clock()
        return StartupProbeResult(
            probe_id=spec.probe_id,
            status=status,
            observed_at=observed_at,
            expires_at=observed_at + timedelta(seconds=self._budget.per_probe_timeout_seconds),
            latency_ms=0,
            failure_class=failure_class,
        )

    async def _publish_transition(
        self,
        previous_decision: str | None,
        report: StartupReadinessReport,
    ) -> None:
        material = f"{previous_decision}|{report.decision.value}|{report.generated_at.isoformat()}"
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        event = Event(
            schema_version="1.0.0",
            event_id=uuid5(NAMESPACE_URL, material),
            idempotency_key=f"startup-readiness:{digest}",
            source="runtime.startup",
            event_type="readiness_transition",
            payload={
                "previous_decision": previous_decision,
                "decision": report.decision.value,
                "missing_probe_ids": list(report.missing_probe_ids),
                "stale_probe_ids": list(report.stale_probe_ids),
                "authority_ceilings": {
                    key: value.value for key, value in report.authority_ceilings.items()
                },
            },
            detected_at=report.generated_at,
            ingested_at=report.generated_at,
            incident_correlation=IncidentCorrelation.NONE,
            mode=Mode.SHADOW,
        )
        payload = event.model_dump(mode="json")
        self._event_validator.validate(payload)
        audit = {
            "kind": "startup_readiness.transition",
            "event_id": str(event.event_id),
            "correlation_id": None,
            "tier": "t0",
            "decision": report.decision.value,
            "idempotency_key": event.idempotency_key,
            "actor_identity": "runtime.startup",
            "timestamp": report.generated_at.isoformat(),
            "mode": "shadow",
            "rollback_reference": None,
            "previous_decision": previous_decision,
        }
        await self._state_store.append_audit_entry(audit)
        try:
            await self._event_bus.publish(_TRANSITION_TOPIC, "runtime", payload)
        except Exception as exc:  # noqa: BLE001 - retain blocked report when transport is down
            await self._state_store.append_audit_entry(
                {
                    **audit,
                    "kind": "startup_readiness.transition_publish_failed",
                    "idempotency_key": f"{event.idempotency_key}:publish-failed",
                    "error_type": type(exc).__name__,
                }
            )


# Severity ordering shared with the posture report; kept local so the coordinator
# imports only shared types (no core-sibling dependency).
_SEVERITY_ORDER: tuple[Severity, ...] = ("low", "medium", "high", "critical")
_SEVERITY_RANK: dict[str, int] = {s: i for i, s in enumerate(_SEVERITY_ORDER)}
# An unrecognized severity outranks every known one, so a finding whose severity
# the coordinator does not understand fails toward safety (treated as blocking)
# rather than crashing the whole handoff gate. Severity is a Literal, not a
# runtime-checked enum, so a fork projection or a deserialized finding can carry
# an unexpected value.
_UNKNOWN_SEVERITY_RANK = len(_SEVERITY_ORDER)


def _severity_rank(severity: str) -> int:
    return _SEVERITY_RANK.get(severity, _UNKNOWN_SEVERITY_RANK)


# The stages that resolve to non-prod on the authoritative runtime classifier
# (risk-classification.md Environment Detection / Promotion). Everything else -
# `prod`, `production`, an unknown word, or a blank - resolves to prod, the
# documented fail-safe (an un-tagged / unrecognized handoff is gated at the
# strictest level, never the weakest).
_NON_PROD_STAGES: frozenset[str] = frozenset({"non-prod", "dev", "test", "staging", "qa"})


def _is_prod_target(target_environment: str) -> bool:
    """True when the handoff target is gated as prod.

    Fail-safe per risk-classification.md: only a recognized non-prod stage
    (case-insensitive) escapes the prod gate; `production`, an unknown value, or
    a blank all resolve to prod - the exact opposite of an ``== "prod"`` check,
    which would fail open on `production` / unknown.
    """
    return target_environment.strip().lower() not in _NON_PROD_STAGES


def compose_readiness_report(
    *,
    signal: OwnershipTransfer,
    posture_findings: Sequence[Finding],
    preflight_findings: Sequence[ProbeFinding],
    mode: Mode,
    generated_at: str,
    blocking_min_severity: Severity = "high",
) -> ReadinessReport:
    """Compose the posture + preflight findings into one handoff verdict.

    A posture finding gates when its severity is at or above
    ``blocking_min_severity`` (config; default ``high``), OR - the environment
    gate - the target is ``prod`` and the finding is ``critical``, regardless of
    the threshold (operational-readiness.md "Environment promotion"). A preflight
    finding gates when its own severity is ``BLOCKING``. The verdict is
    ``blocked`` if any finding gates, ``needs_review`` if findings exist but none
    gates, ``clear`` if there are none.

    A posture finding whose severity is not one of the known levels fails toward
    safety (treated as blocking). ``blocking_min_severity`` is config and MUST be
    a known level - an invalid value raises :class:`ValueError` at the boundary.
    """
    if blocking_min_severity not in _SEVERITY_RANK:
        raise ValueError(
            f"blocking_min_severity {blocking_min_severity!r} is not a known severity "
            f"(expected one of {list(_SEVERITY_ORDER)})"
        )
    min_rank = _SEVERITY_RANK[blocking_min_severity]
    # Match the prod environment fail-safe (risk-classification.md): `prod`,
    # `production`, an unknown word, or a blank all gate as prod - only a
    # recognized non-prod stage escapes it. The report still records the
    # operator's original environment string; only the gate decision is derived.
    prod = _is_prod_target(signal.target_environment)
    findings: list[ReadinessFinding] = []

    for f in posture_findings:
        blocking = _severity_rank(f.severity) >= min_rank or (prod and f.severity == "critical")
        findings.append(
            ReadinessFinding(
                evidence=f.rule_id,
                severity=f.severity,
                resource=f.resource.ref,
                blocking=blocking,
                # The delivery layer resolves the remediation lever from the
                # cited rule; the coordinator never invents one.
                resolution=None,
                source="assurance_twin",
            )
        )

    for pf in preflight_findings:
        findings.append(
            ReadinessFinding(
                evidence=pf.id,
                severity=pf.severity.value,
                resource=signal.scope,
                blocking=pf.severity is FindingSeverity.BLOCKING,
                resolution=pf.resolution.guidance,
                source="deploy_preflight",
                dimension=pf.category.value,
            )
        )

    findings_t = tuple(findings)
    if not findings_t:
        verdict = HandoffVerdict.CLEAR
    elif any(f.blocking for f in findings_t):
        verdict = HandoffVerdict.BLOCKED
    else:
        verdict = HandoffVerdict.NEEDS_REVIEW

    return ReadinessReport(
        scope=signal.scope,
        submitter=signal.submitter,
        target_environment=signal.target_environment,
        generated_at=generated_at,
        mode=mode,
        verdict=verdict,
        findings=findings_t,
    )


__all__ = [
    "StartupProbeBudget",
    "StartupReadinessCoordinator",
    "compose_readiness_report",
]
