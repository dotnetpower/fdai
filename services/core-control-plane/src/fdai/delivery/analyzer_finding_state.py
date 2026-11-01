"""Project only acknowledged analyzer observations into durable current Findings."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from fdai_service_contracts.finding_state import (
    FINDING_STATE_PREFIX,
    FindingState,
    finding_identity,
    is_operational_finding,
)

from fdai.delivery.analyzer_finding_receipt import (
    AnalyzerFindingReceipt,
    AnalyzerPublicationStatus,
)
from fdai.shared.providers.state_store import StateStore

_DELIVERED = {
    AnalyzerPublicationStatus.PUBLISHED,
    AnalyzerPublicationStatus.RECONCILED_DUPLICATE,
    AnalyzerPublicationStatus.DUPLICATE_SUPPRESSED,
}
_PRIORITY: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass(frozen=True, slots=True)
class AnalyzerFindingStateStore:
    state_store: StateStore
    max_cas_attempts: int = 8

    def __post_init__(self) -> None:
        if type(self.max_cas_attempts) is not int or not 1 <= self.max_cas_attempts <= 64:
            raise ValueError("AnalyzerFindingStateStore.max_cas_attempts MUST be 1..64")

    async def record(self, receipt: AnalyzerFindingReceipt) -> None:
        """CAS a derived projection; publication failure and missing data never resolve it.

        Legacy receipts without structured severity are history only. Routine healthy
        observations cannot introduce a Finding. Current rows have no history eviction.
        """
        if receipt.publication not in _DELIVERED or receipt.severity is None:
            return
        if (
            not is_operational_finding(receipt.signal, receipt.assessment_status)
            and receipt.recovery_closed is not True
        ):
            return
        if len(receipt.observation) > 2048:
            raise ValueError("Finding observation exceeds its presentation bound")
        if (receipt.recovery_finding_ref is None) != (receipt.recovery_prior_revision is None):
            raise ValueError("Finding recovery concurrency descriptor is incomplete")
        identity = finding_identity(receipt.resource_kind, receipt.resource_ref, receipt.signal)
        key = f"{FINDING_STATE_PREFIX}{identity}"
        value = receipt.to_dict()
        stable = {
            name: item
            for name, item in value.items()
            if name not in {"publication", "recorded_at", "detection_latency_seconds"}
        }
        stable.update(
            severity=receipt.severity.value,
            observation=receipt.observation,
            assessment_status=receipt.assessment_status,
        )
        digest = hashlib.sha256(
            json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        for _ in range(self.max_cas_attempts):
            stored = await self.state_store.read_state(key)
            previous = FindingState.model_validate(stored) if stored is not None else None
            if previous is not None:
                if receipt.idempotency_key == previous.observation_key:
                    if digest != previous.observation_digest:
                        raise ValueError("Finding observation identity collision")
                    return
                if receipt.occurred_at <= previous.occurred_at:
                    return
            if receipt.recovery_prior_revision is not None and (
                previous is None
                or previous.finding_id != receipt.recovery_finding_ref
                or previous.revision != receipt.recovery_prior_revision
                or previous.status != "active"
            ):
                raise ValueError("Finding recovery no longer matches its active prior revision")
            recovered = (
                receipt.recovery_closed is True
                and receipt.evidence_complete
                and receipt.assessed_by is not None
            )
            if receipt.recovery_closed is True and not recovered:
                raise ValueError("Finding recovery requires a complete canonical assessment")
            historical_fault = (
                receipt.signal in {"container_restart", "pod_replacement"}
                and receipt.assessment_status == receipt.signal
            )
            if previous is None and recovered and not historical_fault:
                return
            status: Literal["active", "resolved"] = "resolved" if recovered else "active"
            reason: Literal["opened", "escalated", "recovered"] | None = None
            if previous is None or (previous.status == "resolved" and status == "active"):
                reason = "opened"
            elif previous.status == "active" and recovered:
                reason = "recovered"
            elif (
                previous.status == "active"
                and status == "active"
                and _PRIORITY[receipt.severity] > _PRIORITY[previous.severity]
            ):
                reason = "escalated"
            if reason is None and previous is not None:
                notification_reason = previous.notification_reason
                notification_changed_at = previous.notification_changed_at
            else:
                notification_reason = reason or "opened"
                notification_changed_at = receipt.recorded_at or receipt.occurred_at
            current = FindingState(
                finding_id=identity,
                revision=1 if previous is None else previous.revision + 1,
                notification_version=(
                    1
                    if previous is None
                    else previous.notification_version + int(reason is not None)
                ),
                notification_reason=notification_reason,
                notification_changed_at=notification_changed_at,
                resource_ref=receipt.resource_ref,
                resource_kind=receipt.resource_kind,
                signal=receipt.signal,
                severity=previous.severity if recovered and previous else receipt.severity.value,
                status=status,
                observation=receipt.observation,
                observation_key=receipt.idempotency_key,
                observation_digest=digest,
                first_seen_at=previous.first_seen_at if previous else receipt.occurred_at,
                occurred_at=receipt.occurred_at,
                recorded_at=receipt.recorded_at or receipt.occurred_at,
                current_state=receipt.assessment_status or receipt.current_state,
                evidence_complete=receipt.evidence_complete,
                evidence_state=str(value["evidence_state"]),
                recovery_closed=receipt.recovery_closed,
                assessed_by=receipt.assessed_by,
                evidence_refs=receipt.evidence_refs,
                evidence_gaps=receipt.evidence_gaps,
                publication=receipt.publication.value,
            )
            updated = current.model_dump(mode="json")
            if previous is None:
                if await self.state_store.write_state_if_absent(key, updated):
                    return
            elif await self.state_store.compare_and_set_state(
                key,
                updated,
                expected_revision=previous.revision,
            ):
                return
        raise RuntimeError("Finding projection contention exceeded its bounded retry budget")
