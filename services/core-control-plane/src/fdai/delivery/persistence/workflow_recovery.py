"""Durable production adapters for the workflow recovery path.

Every adapter here is a read or relay seam over durable evidence. None of
them decides eligibility, grants execution or approval authority, or claims
independent effect verification on the executor's behalf.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.runbook.models import RunbookStep
from fdai.core.workflow.recovery_attempt import (
    RecoveryAttemptIdentity,
    RecoveryDispatchOutcome,
    RecoveryDispatchResult,
    RecoveryPreDispatchClaim,
)
from fdai.core.workflow.recovery_coordinator import RecoveryEffectObservation
from fdai.core.workflow.recovery_effect_claim import (
    EffectEvidenceClass,
    EffectEvidenceRecord,
    FinalizedWatermark,
)
from fdai.core.workflow.workflow_runtime import (
    WorkflowActionDispatcher,
    WorkflowApprovalDecision,
    WorkflowApprovalSnapshot,
    workflow_approval_state_key,
)
from fdai.shared.providers.state_store import StateStore

_BUNDLE_PREFIX = "workflow:recovery-safeguard-bundle:"
_OBSERVATION_PREFIX = "workflow:recovery-effect-observation:"


def recovery_approval_step_id(attempt: RecoveryAttemptIdentity) -> str:
    """Return the deterministic approval step for one recovery attempt.

    The step is derived from the immutable attempt identity, so an approval
    granted for a different attempt, hold revision, or payload can never be
    replayed onto this one.
    """

    return f"recover_{attempt.identity_digest.removeprefix('sha256:')[:32]}"


def recovery_safeguard_bundle_key(attempt: RecoveryAttemptIdentity) -> str:
    """Return the durable key holding the finalized recovery bundle evidence."""

    return f"{_BUNDLE_PREFIX}{attempt.identity_digest.removeprefix('sha256:')}"


def recovery_effect_observation_key(
    attempt: RecoveryAttemptIdentity,
    provider_receipt_digest: str,
) -> str:
    """Return the durable key holding one independent post-effect observation."""

    digest = content_digest(
        {
            "attempt_identity_digest": attempt.identity_digest,
            "provider_receipt_digest": provider_receipt_digest,
        }
    )
    return f"{_OBSERVATION_PREFIX}{digest.removeprefix('sha256:')}"


@dataclass(frozen=True, slots=True)
class StateStoreRecoveryApprovalReader:
    """Resolve the separate immutable human approval bound to one attempt."""

    store: StateStore

    async def recovery_approval(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        process_id: str,
        target_resource_id: str,
    ) -> WorkflowApprovalSnapshot | None:
        """Return the durable recovery approval, or ``None`` when unavailable."""

        del target_resource_id
        record = await self.store.read_state(
            workflow_approval_state_key(
                process_id,
                recovery_approval_step_id(attempt),
                attempt.attempt_number,
            )
        )
        if record is None or record.get("process_id") != process_id:
            return None
        decisions = _decisions(record)
        if decisions is None:
            return None
        requested_at = _aware(record.get("requested_at"))
        revision = _positive_int(record.get("revision"))
        if requested_at is None or revision is None:
            return None
        return WorkflowApprovalSnapshot(
            process_id=process_id,
            step_id=str(record.get("step_id") or ""),
            requester_principal=str(record.get("requester_principal") or ""),
            revision=revision,
            requested_at=requested_at,
            expires_at=_aware(record.get("expires_at")),
            attempt=_positive_int(record.get("attempt")) or 1,
            decisions=decisions,
            timed_out=record.get("state") == "timed_out",
            cancelled=record.get("state") == "cancelled",
        )


@dataclass(frozen=True, slots=True)
class StateStoreRecoverySafeguardBundleReader:
    """Read the finalized safeguard bundle digest bound to one attempt."""

    store: StateStore

    async def finalized_recovery_bundle_digest(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        target_resource_id: str,
    ) -> str | None:
        """Return the bundle digest only when its binding is exact and final."""

        record = await self.store.read_state(recovery_safeguard_bundle_key(attempt))
        if record is None:
            return None
        if (
            record.get("attempt_identity_digest") != attempt.identity_digest
            or record.get("target_digest") != attempt.target_digest
            or record.get("source_revision") != attempt.source_revision
            or record.get("state") != "finalized"
            or record.get("execution_authority") is not False
        ):
            return None
        if record.get("target_resource_digest") not in {
            None,
            _target_evidence_digest(target_resource_id),
        }:
            return None
        digest = record.get("safeguard_bundle_digest")
        return digest if _is_digest(digest) else None


@dataclass(frozen=True, slots=True)
class StateStoreRecoveryEffectObserver:
    """Return one independently recorded authoritative post-effect observation."""

    store: StateStore

    async def observe_recovery_effect(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        target_resource_id: str,
        provider_receipt_digest: str,
        observed_at: datetime,
    ) -> RecoveryEffectObservation | None:
        """Return the durable observation, or ``None`` when it is unavailable."""

        del target_resource_id
        record = await self.store.read_state(
            recovery_effect_observation_key(attempt, provider_receipt_digest)
        )
        if record is None:
            return None
        if (
            record.get("attempt_identity_digest") != attempt.identity_digest
            or record.get("provider_receipt_digest") != provider_receipt_digest
        ):
            return None
        window_start = _aware(record.get("evidence_window_start"))
        window_end = _aware(record.get("evidence_window_end"))
        event_time = _aware(record.get("event_time"))
        recorded_time = _aware(record.get("recorded_time"))
        if None in (window_start, window_end, event_time, recorded_time):
            return None
        assert window_start is not None and window_end is not None  # noqa: S101 - narrowed above
        assert event_time is not None and recorded_time is not None  # noqa: S101 - narrowed above
        if observed_at.astimezone(UTC) < window_end:
            return None
        watermarks = _watermarks(record)
        if not watermarks:
            return None
        authority_class = _authority_class(record.get("observer_authority_class"))
        if authority_class is None:
            return None
        try:
            evidence = EffectEvidenceRecord(
                observer_identity=str(record.get("observer_identity") or ""),
                observer_authority_class=authority_class,
                purpose_version=str(record.get("purpose_version") or ""),
                method_version=str(record.get("method_version") or ""),
                event_time=event_time,
                recorded_time=recorded_time,
                freshness_policy_seconds=_positive_int(record.get("freshness_policy_seconds")) or 0,
                completeness=bool(record.get("completeness")),
                provenance=str(record.get("provenance") or ""),
                conflict_status=str(record.get("conflict_status") or "none"),
                synthetic=bool(record.get("synthetic")),
                evidence_digest=str(record.get("evidence_digest") or ""),
            )
            return RecoveryEffectObservation(
                evidence=evidence,
                observer_identity=evidence.observer_identity,
                provider_identity=str(record.get("provider_identity") or ""),
                expected_effect_digest=str(record.get("expected_effect_digest") or ""),
                approved_envelope_digest=str(record.get("approved_envelope_digest") or ""),
                action_digest=str(record.get("action_digest") or ""),
                evidence_window_start=window_start,
                evidence_window_end=window_end,
                watermarks=watermarks,
                success=bool(record.get("success")),
            )
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class WorkflowActionRecoveryDispatchPort:
    """Republish one claimed recovery attempt into the typed action ingress."""

    dispatcher: WorkflowActionDispatcher
    store: StateStore

    async def dispatch_recovery(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        claim: RecoveryPreDispatchClaim,
        safeguard_bundle_digest: str,
        target_resource_id: str,
        params: Mapping[str, object],
        correlation_id: str,
    ) -> RecoveryDispatchResult:
        """Dispatch once under the claim; an unresolved provider stays in doubt."""

        step = RunbookStep(
            id=recovery_approval_step_id(attempt),
            action_type=attempt.recovery_action_type,
            params=dict(params),
        )
        try:
            proposal_ref = await self.dispatcher.dispatch(
                process_id=attempt.process_id,
                correlation_id=correlation_id,
                step=step,
                target_resource_id=target_resource_id,
                params=step.params,
                context={
                    "recovery.attempt_identity_digest": attempt.identity_digest,
                    "recovery.claim_digest": claim.claim_digest,
                    "recovery.idempotency_key": claim.idempotency_key,
                    "recovery.safeguard_bundle_digest": safeguard_bundle_digest,
                },
                attempt=attempt.attempt_number,
            )
        except Exception:  # noqa: BLE001 - transport doubt is never a non-invocation
            return RecoveryDispatchResult.create(
                attempt_identity_digest=attempt.identity_digest,
                claim_digest=claim.claim_digest,
                outcome=RecoveryDispatchOutcome.IN_DOUBT,
                provider_receipt_digest=None,
                recorded_at=datetime.now(tz=UTC),
            )
        if not proposal_ref.strip():
            return RecoveryDispatchResult.create(
                attempt_identity_digest=attempt.identity_digest,
                claim_digest=claim.claim_digest,
                outcome=RecoveryDispatchOutcome.IN_DOUBT,
                provider_receipt_digest=None,
                recorded_at=datetime.now(tz=UTC),
            )
        return RecoveryDispatchResult.create(
            attempt_identity_digest=attempt.identity_digest,
            claim_digest=claim.claim_digest,
            outcome=RecoveryDispatchOutcome.DISPATCHED,
            provider_receipt_digest=content_digest(
                {
                    "domain": "workflow-recovery-proposal-reference",
                    "proposal_ref": proposal_ref,
                }
            ),
            recorded_at=datetime.now(tz=UTC),
        )

    async def reconcile_recovery(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        claim: RecoveryPreDispatchClaim,
    ) -> RecoveryDispatchResult | None:
        """Resolve an in-doubt dispatch from the durable provider receipt only."""

        record = await self.store.find_state(
            _OBSERVATION_PREFIX,
            field="attempt_identity_digest",
            value=attempt.identity_digest,
        )
        if record is None:
            return None
        receipt = record.get("provider_receipt_digest")
        if not _is_digest(receipt):
            return None
        return RecoveryDispatchResult.create(
            attempt_identity_digest=attempt.identity_digest,
            claim_digest=claim.claim_digest,
            outcome=RecoveryDispatchOutcome.DISPATCHED,
            provider_receipt_digest=str(receipt),
            recorded_at=datetime.now(tz=UTC),
        )


def _decisions(record: Mapping[str, Any]) -> tuple[WorkflowApprovalDecision, ...] | None:
    raw = record.get("decision_claims")
    if not isinstance(raw, Mapping):
        return None
    decisions: list[WorkflowApprovalDecision] = []
    for claim in raw.values():
        if not isinstance(claim, Mapping):
            return None
        try:
            decisions.append(
                WorkflowApprovalDecision(
                    principal=str(claim.get("principal") or ""),
                    decision=str(claim.get("decision") or ""),
                    receipt_ref=str(claim.get("receipt_ref") or ""),
                )
            )
        except ValueError:
            return None
    return tuple(decisions)


def _watermarks(record: Mapping[str, Any]) -> tuple[FinalizedWatermark, ...]:
    raw = record.get("watermarks")
    if not isinstance(raw, list):
        return ()
    watermarks: list[FinalizedWatermark] = []
    for item in raw:
        if not isinstance(item, Mapping):
            return ()
        watermark = _aware(item.get("watermark"))
        if watermark is None:
            return ()
        try:
            watermarks.append(
                FinalizedWatermark(
                    source_id=str(item.get("source_id") or ""),
                    watermark=watermark,
                    final=bool(item.get("final")),
                    watermark_digest=str(item.get("watermark_digest") or ""),
                )
            )
        except ValueError:
            return ()
    return tuple(watermarks)


def _authority_class(value: object) -> EffectEvidenceClass | None:
    if not isinstance(value, str):
        return None
    try:
        return EffectEvidenceClass(value)
    except ValueError:
        return None


def _aware(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str) and value.startswith("sha256:") and len(value) == len("sha256:") + 64
    )


def _target_evidence_digest(target_ref: str) -> str:
    return f"sha256:{hashlib.sha256(target_ref.encode()).hexdigest()}"


__all__ = [
    "StateStoreRecoveryApprovalReader",
    "StateStoreRecoveryEffectObserver",
    "StateStoreRecoverySafeguardBundleReader",
    "WorkflowActionRecoveryDispatchPort",
    "recovery_approval_step_id",
    "recovery_effect_observation_key",
    "recovery_safeguard_bundle_key",
]
