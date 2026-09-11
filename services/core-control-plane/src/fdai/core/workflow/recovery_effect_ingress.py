"""Versioned typed ingress for independent recovery effect observations (#656).

A recovery effect is only verified when an authority that is independent of the
executor and of the provider reports it. This module is the one production entry
point that authority writes through. It belongs to the observer path: it accepts
a versioned typed event, proves the reporting principal is an authorized
observer rather than the executor, proves the evidence is externally
authoritative, final, contained, fresh, and bound to one persisted recovery
attempt, and only then asks the journal to persist it.

Persisting is never verifying. The recovery coordinator still re-reads the
durable observation and re-applies identity separation, finality, and admission
before any completion claim, so nothing here grants effect-verification or
execution authority.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from fdai.core.workflow.recovery_attempt import (
    RecoveryAttemptIdentity,
    is_recovery_attempt_step_id,
)
from fdai.core.workflow.recovery_coordinator import RecoveryEffectObservation
from fdai.core.workflow.recovery_effect_claim import (
    EffectEvidenceClass,
    EffectEvidenceRecord,
    FinalizedWatermark,
)

RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE = "workflow.recovery.effect_observed.v1"
"""Versioned event type an independent observer publishes on the observer path."""

RECOVERY_EFFECT_OBSERVATION_SCHEMA_VERSION = "1.0.0"
"""Current payload schema version of the independent observation envelope.

The field is named `observation_schema_version` on the wire because the event
bus already owns `schema_version` for its own envelope, and an observation must
never be validated against a version another layer set.
"""

SUPPORTED_RECOVERY_EFFECT_OBSERVATION_SCHEMA_VERSIONS = frozenset(
    {RECOVERY_EFFECT_OBSERVATION_SCHEMA_VERSION}
)
"""Every payload schema version this ingress accepts."""

DEFAULT_RECOVERY_EFFECT_OBSERVER_PRINCIPALS = frozenset({"Heimdall", "Huginn"})
"""Principals allowed to publish an independent recovery effect observation.

Both are sensing or observer principals. The sole privileged executor is never
in this set, so an executor-published observation is refused on identity before
any evidence is read.
"""

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_MAX_TEXT = 512


class RecoveryEffectObservationRejection(StrEnum):
    """Why one independent observation event was refused."""

    EVENT_TYPE_UNSUPPORTED = "event_type_unsupported"
    SCHEMA_VERSION_UNSUPPORTED = "schema_version_unsupported"
    MALFORMED_PAYLOAD = "malformed_payload"
    OBSERVER_UNAUTHENTICATED = "observer_unauthenticated"
    OBSERVER_NOT_AUTHORIZED = "observer_not_authorized"
    OBSERVER_NOT_INDEPENDENT = "observer_not_independent"
    AUTHORITY_CLASS_INELIGIBLE = "authority_class_ineligible"
    SYNTHETIC_EVIDENCE = "synthetic_evidence"
    ATTEMPT_UNKNOWN = "attempt_unknown"
    ATTEMPT_MISMATCH = "attempt_mismatch"
    TARGET_MISMATCH = "target_mismatch"
    PROVIDER_RECEIPT_INVALID = "provider_receipt_invalid"
    EVIDENCE_WINDOW_INVALID = "evidence_window_invalid"
    EVIDENCE_STALE = "evidence_stale"
    FINALITY_INCOMPLETE = "finality_incomplete"
    CONTAINMENT_UNPROVEN = "containment_unproven"
    CONFLICTING_OBSERVATION = "conflicting_observation"
    INTAKE_UNBOUND = "intake_unbound"
    NOT_PERSISTED = "not_persisted"


class RecoveryEffectObservationWrite(StrEnum):
    """Durable outcome of one independent observation write."""

    RECORDED = "recorded"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    REFUSED = "refused"


@runtime_checkable
class IndependentRecoveryEffectObservationJournal(Protocol):
    """Persist one independent authoritative post-effect observation."""

    async def record_independent_observation(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        target_resource_id: str,
        provider_receipt_digest: str,
        observation: RecoveryEffectObservation,
    ) -> RecoveryEffectObservationWrite: ...


@runtime_checkable
class RecoveryAttemptResolver(Protocol):
    """Resolve the persisted recovery attempt one workflow step belongs to."""

    async def resolve_recovery_attempt(
        self,
        *,
        process_id: str,
        recovery_step_id: str,
    ) -> RecoveryAttemptIdentity | None: ...


@dataclass(frozen=True, slots=True)
class RecoveryEffectObservationIngressResult:
    """Immutable ingress outcome that grants no verification authority."""

    accepted: bool
    write: RecoveryEffectObservationWrite
    rejection: RecoveryEffectObservationRejection | None = None
    attempt_identity_digest: str | None = None
    evidence_digest: str | None = None
    effect_verification_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.effect_verification_authority or self.execution_authority:
            raise ValueError("recovery effect observation ingress MUST NOT grant authority")
        if self.accepted and self.rejection is not None:
            raise ValueError("an accepted observation MUST NOT carry a rejection")
        if not self.accepted and self.rejection is None:
            raise ValueError("a refused observation MUST name its rejection")

    @property
    def duplicate(self) -> bool:
        """Whether this event repeated an already durable observation."""

        return self.write is RecoveryEffectObservationWrite.DUPLICATE


@dataclass(frozen=True, slots=True)
class RecoveryEffectObservationIngress:
    """Accept independent post-effect observations on the observer path.

    ``executor_identity`` and ``authorized_principals`` are configuration, not
    payload: an event can never nominate the identity it is checked against.
    """

    attempts: RecoveryAttemptResolver
    journal: IndependentRecoveryEffectObservationJournal | None
    executor_identity: str
    authorized_principals: frozenset[str] = DEFAULT_RECOVERY_EFFECT_OBSERVER_PRINCIPALS
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(tz=UTC))

    async def observe(
        self,
        payload: Mapping[str, Any],
        *,
        authenticated_principal: str,
    ) -> RecoveryEffectObservationIngressResult:
        """Validate one versioned observation event and persist it once."""

        rejection = self._check_envelope(payload, authenticated_principal)
        if rejection is not None:
            return _refused(rejection)

        process_id = _text(payload.get("process_id"))
        recovery_step_id = _text(payload.get("recovery_step_id"))
        if not process_id or not is_recovery_attempt_step_id(recovery_step_id):
            return _refused(RecoveryEffectObservationRejection.MALFORMED_PAYLOAD)
        attempt = await self.attempts.resolve_recovery_attempt(
            process_id=process_id,
            recovery_step_id=recovery_step_id,
        )
        if attempt is None:
            return _refused(RecoveryEffectObservationRejection.ATTEMPT_UNKNOWN)
        if payload.get("attempt_identity_digest") != attempt.identity_digest:
            return _refused(RecoveryEffectObservationRejection.ATTEMPT_MISMATCH)

        target_resource_id = _text(payload.get("target_resource_id"))
        if not target_resource_id or _target_evidence_digest(target_resource_id) != (
            attempt.target_digest
        ):
            return _refused(RecoveryEffectObservationRejection.TARGET_MISMATCH)
        provider_receipt_digest = _text(payload.get("provider_receipt_digest"))
        if _DIGEST.fullmatch(provider_receipt_digest) is None:
            return _refused(RecoveryEffectObservationRejection.PROVIDER_RECEIPT_INVALID)

        built = _build_observation(payload)
        if isinstance(built, RecoveryEffectObservationRejection):
            return _refused(built)
        rejection = self._check_evidence(built)
        if rejection is not None:
            return _refused(rejection)

        journal = self.journal
        if journal is None:
            return _refused(RecoveryEffectObservationRejection.INTAKE_UNBOUND)
        write = await journal.record_independent_observation(
            attempt=attempt,
            target_resource_id=target_resource_id,
            provider_receipt_digest=provider_receipt_digest,
            observation=built,
        )
        if write is RecoveryEffectObservationWrite.CONFLICT:
            return _refused(
                RecoveryEffectObservationRejection.CONFLICTING_OBSERVATION,
                attempt_identity_digest=attempt.identity_digest,
                write=write,
            )
        if write is RecoveryEffectObservationWrite.REFUSED:
            return _refused(
                RecoveryEffectObservationRejection.NOT_PERSISTED,
                attempt_identity_digest=attempt.identity_digest,
                write=write,
            )
        return RecoveryEffectObservationIngressResult(
            accepted=True,
            write=write,
            attempt_identity_digest=attempt.identity_digest,
            evidence_digest=built.evidence.evidence_digest,
        )

    def _check_envelope(
        self,
        payload: Mapping[str, Any],
        authenticated_principal: str,
    ) -> RecoveryEffectObservationRejection | None:
        """Refuse an event whose version or reporting principal is unusable."""

        if payload.get("event_type") != RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE:
            return RecoveryEffectObservationRejection.EVENT_TYPE_UNSUPPORTED
        version = payload.get("observation_schema_version")
        if (
            not isinstance(version, str)
            or version not in SUPPORTED_RECOVERY_EFFECT_OBSERVATION_SCHEMA_VERSIONS
        ):
            return RecoveryEffectObservationRejection.SCHEMA_VERSION_UNSUPPORTED
        principal = authenticated_principal.strip()
        if not principal:
            return RecoveryEffectObservationRejection.OBSERVER_UNAUTHENTICATED
        if principal not in self.authorized_principals:
            return RecoveryEffectObservationRejection.OBSERVER_NOT_AUTHORIZED
        if principal.casefold() == self.executor_identity.strip().casefold():
            return RecoveryEffectObservationRejection.OBSERVER_NOT_INDEPENDENT
        declared = payload.get("producer_principal")
        if declared is not None and declared != principal:
            return RecoveryEffectObservationRejection.OBSERVER_UNAUTHENTICATED
        return None

    def _check_evidence(
        self,
        observation: RecoveryEffectObservation,
    ) -> RecoveryEffectObservationRejection | None:
        """Refuse evidence the executor owns, or that is unfinal or stale."""

        evidence = observation.evidence
        observer = evidence.observer_identity.strip().casefold()
        if observer in {
            self.executor_identity.strip().casefold(),
            observation.provider_identity.strip().casefold(),
        }:
            return RecoveryEffectObservationRejection.OBSERVER_NOT_INDEPENDENT
        if evidence.observer_authority_class is not EffectEvidenceClass.AUTHORITATIVE_EXTERNAL:
            return RecoveryEffectObservationRejection.AUTHORITY_CLASS_INELIGIBLE
        if not evidence.completeness or evidence.conflict_status != "none":
            return RecoveryEffectObservationRejection.FINALITY_INCOMPLETE
        if not observation.finalized:
            return RecoveryEffectObservationRejection.FINALITY_INCOMPLETE
        now = self.clock().astimezone(UTC)
        if evidence.recorded_time.astimezone(UTC) < evidence.event_time.astimezone(UTC):
            return RecoveryEffectObservationRejection.EVIDENCE_WINDOW_INVALID
        window_end = observation.evidence_window_end.astimezone(UTC)
        if window_end > now:
            return RecoveryEffectObservationRejection.EVIDENCE_WINDOW_INVALID
        if now - window_end > timedelta(seconds=evidence.freshness_policy_seconds):
            return RecoveryEffectObservationRejection.EVIDENCE_STALE
        return None


def _build_observation(
    payload: Mapping[str, Any],
) -> RecoveryEffectObservation | RecoveryEffectObservationRejection:
    """Rebuild the typed observation, or name why the payload is unusable."""

    if payload.get("forbidden_effect_observed") is not False or (
        payload.get("envelope_contained") is not True
    ):
        return RecoveryEffectObservationRejection.CONTAINMENT_UNPROVEN
    success = payload.get("success")
    completeness = payload.get("completeness")
    synthetic = payload.get("synthetic")
    if (
        not isinstance(success, bool)
        or not isinstance(completeness, bool)
        or not isinstance(synthetic, bool)
    ):
        return RecoveryEffectObservationRejection.MALFORMED_PAYLOAD
    if synthetic:
        return RecoveryEffectObservationRejection.SYNTHETIC_EVIDENCE
    authority_class = _authority_class(payload.get("observer_authority_class"))
    if authority_class is None:
        return RecoveryEffectObservationRejection.AUTHORITY_CLASS_INELIGIBLE
    event_time = _aware(payload.get("event_time"))
    recorded_time = _aware(payload.get("recorded_time"))
    window_start = _aware(payload.get("evidence_window_start"))
    window_end = _aware(payload.get("evidence_window_end"))
    freshness = payload.get("freshness_policy_seconds")
    if (
        event_time is None
        or recorded_time is None
        or window_start is None
        or window_end is None
        or not isinstance(freshness, int)
        or isinstance(freshness, bool)
        or freshness < 0
    ):
        return RecoveryEffectObservationRejection.MALFORMED_PAYLOAD
    if window_end <= window_start:
        return RecoveryEffectObservationRejection.EVIDENCE_WINDOW_INVALID
    watermarks = _watermarks(payload.get("watermarks"))
    if watermarks is None:
        return RecoveryEffectObservationRejection.MALFORMED_PAYLOAD
    if not watermarks:
        return RecoveryEffectObservationRejection.FINALITY_INCOMPLETE
    digests = {
        key: _text(payload.get(key))
        for key in (
            "evidence_digest",
            "expected_effect_digest",
            "approved_envelope_digest",
            "action_digest",
        )
    }
    if any(_DIGEST.fullmatch(value) is None for value in digests.values()):
        return RecoveryEffectObservationRejection.MALFORMED_PAYLOAD
    observer_identity = _text(payload.get("observer_identity"))
    provider_identity = _text(payload.get("provider_identity"))
    provenance = _text(payload.get("provenance"))
    purpose_version = _text(payload.get("purpose_version"))
    method_version = _text(payload.get("method_version"))
    if (
        not observer_identity
        or not provider_identity
        or not provenance
        or not purpose_version
        or not method_version
    ):
        return RecoveryEffectObservationRejection.MALFORMED_PAYLOAD
    try:
        evidence = EffectEvidenceRecord(
            observer_identity=observer_identity,
            observer_authority_class=authority_class,
            purpose_version=purpose_version,
            method_version=method_version,
            event_time=event_time,
            recorded_time=recorded_time,
            freshness_policy_seconds=freshness,
            completeness=completeness,
            provenance=provenance,
            conflict_status=_text(payload.get("conflict_status")) or "unknown",
            synthetic=synthetic,
            evidence_digest=digests["evidence_digest"],
        )
        return RecoveryEffectObservation(
            evidence=evidence,
            observer_identity=observer_identity,
            provider_identity=provider_identity,
            expected_effect_digest=digests["expected_effect_digest"],
            approved_envelope_digest=digests["approved_envelope_digest"],
            action_digest=digests["action_digest"],
            evidence_window_start=window_start,
            evidence_window_end=window_end,
            watermarks=watermarks,
            success=success,
        )
    except ValueError:
        return RecoveryEffectObservationRejection.MALFORMED_PAYLOAD


def _refused(
    rejection: RecoveryEffectObservationRejection,
    *,
    attempt_identity_digest: str | None = None,
    write: RecoveryEffectObservationWrite = RecoveryEffectObservationWrite.REFUSED,
) -> RecoveryEffectObservationIngressResult:
    return RecoveryEffectObservationIngressResult(
        accepted=False,
        write=write,
        rejection=rejection,
        attempt_identity_digest=attempt_identity_digest,
    )


def _authority_class(value: object) -> EffectEvidenceClass | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = EffectEvidenceClass(value)
    except ValueError:
        return None
    return parsed if parsed is EffectEvidenceClass.AUTHORITATIVE_EXTERNAL else None


def _watermarks(value: object) -> tuple[FinalizedWatermark, ...] | None:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return None
    watermarks: list[FinalizedWatermark] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            return None
        watermark = _aware(raw.get("watermark"))
        final = raw.get("final")
        source_id = _text(raw.get("source_id"))
        digest = _text(raw.get("watermark_digest"))
        if watermark is None or not isinstance(final, bool) or not source_id:
            return None
        if _DIGEST.fullmatch(digest) is None:
            return None
        watermarks.append(
            FinalizedWatermark(
                source_id=source_id,
                watermark=watermark,
                final=final,
                watermark_digest=digest,
            )
        )
    return tuple(watermarks)


def _aware(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > _MAX_TEXT:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _text(value: object) -> str:
    if not isinstance(value, str) or len(value) > _MAX_TEXT:
        return ""
    return value.strip()


def _target_evidence_digest(target_ref: str) -> str:
    return f"sha256:{hashlib.sha256(target_ref.encode()).hexdigest()}"


__all__ = [
    "DEFAULT_RECOVERY_EFFECT_OBSERVER_PRINCIPALS",
    "RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE",
    "RECOVERY_EFFECT_OBSERVATION_SCHEMA_VERSION",
    "SUPPORTED_RECOVERY_EFFECT_OBSERVATION_SCHEMA_VERSIONS",
    "IndependentRecoveryEffectObservationJournal",
    "RecoveryAttemptResolver",
    "RecoveryEffectObservationIngress",
    "RecoveryEffectObservationIngressResult",
    "RecoveryEffectObservationRejection",
    "RecoveryEffectObservationWrite",
]
