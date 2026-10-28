"""Read-only recovery dispatch over exact, verified persisted fault Findings."""

from __future__ import annotations

import asyncio
from collections.abc import Collection, Sequence
from dataclasses import replace
from typing import Protocol, runtime_checkable

from fdai_service_contracts.finding_state import (
    FINDING_STATE_PREFIX,
    FindingState,
    finding_identity,
)
from pydantic import ValidationError

from fdai.core.investigation.analyzer import ResourceAnalyzer
from fdai.core.investigation.contract import AnalyzerFinding, FindingAssessment
from fdai.core.investigation.host_cpu import HOST_CPU_ASSESSOR
from fdai.core.investigation.kubernetes_pod_status import (
    POD_STATUS_ASSESSOR,
    POD_STATUS_FAULT_SIGNALS,
)
from fdai.core.investigation.resource_availability_evidence import (
    RESOURCE_AVAILABILITY_ASSESSOR,
)
from fdai.delivery.analyzer_finding_receipt import AnalyzerPublicationStatus
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.state_store import StateStore

_FAULT_STATUSES = {
    "host_cpu": frozenset({"cpu_threshold_observed"}),
    "resource_availability": frozenset(
        {
            "stop_observed",
            "expected_running_not_observed",
            "expected_stop_not_observed",
        }
    ),
    **{signal: frozenset({signal}) for signal in POD_STATUS_FAULT_SIGNALS},
}
_ASSESSORS = {
    "host_cpu": HOST_CPU_ASSESSOR,
    "resource_availability": RESOURCE_AVAILABILITY_ASSESSOR,
    **dict.fromkeys(POD_STATUS_FAULT_SIGNALS, POD_STATUS_ASSESSOR),
}
_DELIVERED = frozenset(
    {
        AnalyzerPublicationStatus.PUBLISHED.value,
        AnalyzerPublicationStatus.DUPLICATE_SUPPRESSED.value,
        AnalyzerPublicationStatus.RECONCILED_DUPLICATE.value,
    }
)
_STATE_READ_TIMEOUT_SECONDS = 10.0


@runtime_checkable
class SupportsAnalyzerRecovery(Protocol):
    """Optional extension; ResourceAnalyzer itself stays unchanged."""

    async def analyze_recovery(
        self,
        *,
        prior_finding: AnalyzerFinding,
        finding_ref: str,
        window_seconds: float,
    ) -> Sequence[AnalyzerFinding]: ...


class AnalyzerRecoveryStateError(RuntimeError):
    """Recovery context is unavailable, corrupt, or changed during observation."""


class RecoveryAwareAnalyzer:
    """Normal detection first, then positive recovery only for a prior actual fault.

    ``recoverable_signals`` selects reviewed host/resource/Pod leaf contracts.
    The parent's current-state writer must retain their canonical assessment
    status in ``current_state``. Legacy, gap-only, resolved and unverified rows
    cannot be promoted into fault evidence by parsing observation text.
    Recovery metadata carries a revision for the publication-side CAS; the
    read fence here cannot replace that final concurrent-update check.
    """

    def __init__(
        self,
        analyzer: ResourceAnalyzer,
        state_store: StateStore,
        recoverable_signals: Collection[str],
    ) -> None:
        signals = frozenset(recoverable_signals)
        if not signals <= _FAULT_STATUSES.keys():
            raise ValueError("recovery signals MUST select reviewed host/resource/Pod observations")
        self._analyzer = analyzer
        self._store = state_store
        self._signals = tuple(sorted(signals))

    @property
    def resource_kind(self) -> str:
        return self._analyzer.resource_kind

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> Sequence[AnalyzerFinding]:
        findings = tuple(
            await self._analyzer.analyze(
                resource_ref=resource_ref,
                window_seconds=window_seconds,
            )
        )
        self._check_identities(findings, resource_ref=resource_ref)
        if not isinstance(self._analyzer, SupportsAnalyzerRecovery):
            return findings
        for signal in self._signals:
            matching = tuple(finding for finding in findings if finding.signal == signal)
            if any(
                finding.assessment is None
                or finding.assessment.assessed_by != _ASSESSORS[signal]
                or finding.assessment.status in _FAULT_STATUSES[signal]
                for finding in matching
            ):
                continue
            identity = finding_identity(self.resource_kind, resource_ref, signal)
            key = f"{FINDING_STATE_PREFIX}{identity}"
            previous = await self._read(key, resource_ref=resource_ref, signal=signal)
            if previous is None or not _is_verified_fault(previous):
                continue
            prior = _prior_finding(previous)
            recovery = tuple(
                await self._analyzer.analyze_recovery(
                    prior_finding=prior,
                    finding_ref=identity,
                    window_seconds=window_seconds,
                )
            )
            self._check_identities(recovery, resource_ref=resource_ref)
            for finding in recovery:
                assessment = finding.assessment
                if (
                    finding.signal != signal
                    or assessment is None
                    or assessment.assessed_by != _ASSESSORS[signal]
                    or identity not in finding.evidence_refs
                ):
                    raise AnalyzerRecoveryStateError(
                        "recovery observation changed its fault binding"
                    )
                if assessment.recovery_closed is True and (
                    not assessment.evidence_complete or finding.occurred_at <= previous.occurred_at
                ):
                    raise AnalyzerRecoveryStateError("recovery requires later positive evidence")
            current = await self._read(key, resource_ref=resource_ref, signal=signal)
            if current != previous:
                raise AnalyzerRecoveryStateError("recovery state changed during observation")
            if recovery:
                findings = (
                    *(finding for finding in findings if finding.signal != signal),
                    *(
                        replace(
                            finding,
                            metadata={
                                **finding.metadata,
                                "recovery_finding_ref": identity,
                                "recovery_prior_revision": str(previous.revision),
                            },
                        )
                        for finding in recovery
                    ),
                )
        return tuple(_with_current_state(finding) for finding in findings)

    async def _read(self, key: str, *, resource_ref: str, signal: str) -> FindingState | None:
        try:
            async with asyncio.timeout(_STATE_READ_TIMEOUT_SECONDS):
                raw = await self._store.read_state(key)
        except Exception:  # noqa: BLE001 - never turn unavailable state into healthy
            raise AnalyzerRecoveryStateError("persisted recovery state is unavailable") from None
        if raw is None:
            return None
        try:
            state = FindingState.model_validate(raw)
        except (ValidationError, TypeError, ValueError):
            raise AnalyzerRecoveryStateError("persisted recovery state is invalid") from None
        if (
            state.finding_id != finding_identity(self.resource_kind, resource_ref, signal)
            or state.resource_kind != self.resource_kind
            or state.resource_ref != resource_ref
            or state.signal != signal
            or state.occurred_at.tzinfo is None
            or state.recorded_at.tzinfo is None
            or state.occurred_at > state.recorded_at
        ):
            raise AnalyzerRecoveryStateError("persisted recovery state changed identity or time")
        return state

    def _check_identities(self, findings: Sequence[AnalyzerFinding], *, resource_ref: str) -> None:
        if any(
            finding.resource_ref != resource_ref or finding.resource_kind != self.resource_kind
            for finding in findings
        ):
            raise AnalyzerRecoveryStateError("analyzer returned another recovery target")


def _is_verified_fault(state: FindingState) -> bool:
    # Pod API status may establish an OOM fault while optional logs are absent.
    # That does not relax the adapter's independent complete-Ready recovery gate.
    prior_evidence_qualified = (
        state.evidence_state in {"complete", "incomplete"}
        if state.signal in POD_STATUS_FAULT_SIGNALS
        else state.evidence_complete
        and state.evidence_state == "complete"
        and not state.evidence_gaps
    )
    return (
        state.status == "active"
        and state.current_state in _FAULT_STATUSES[state.signal]
        and state.assessed_by == _ASSESSORS[state.signal]
        and prior_evidence_qualified
        and state.recovery_closed is not True
        and bool(state.evidence_refs)
        and bool(state.observation.strip())
        and state.publication in _DELIVERED
    )


def _prior_finding(state: FindingState) -> AnalyzerFinding:
    return AnalyzerFinding(
        resource_ref=state.resource_ref,
        resource_kind=state.resource_kind,
        signal=state.signal,
        observation=state.observation,
        severity=Severity(state.severity),
        occurred_at=state.occurred_at,
        evidence_refs=state.evidence_refs,
        assessment=FindingAssessment(
            assessed_by=_ASSESSORS[state.signal],
            evidence_complete=state.evidence_complete,
            recovery_closed=state.recovery_closed,
            status=state.current_state,
            evidence_gaps=state.evidence_gaps,
        ),
    )


def _with_current_state(finding: AnalyzerFinding) -> AnalyzerFinding:
    if finding.assessment is None:
        return finding
    return replace(
        finding,
        metadata={**finding.metadata, "current_state": finding.assessment.status},
    )
