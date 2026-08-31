"""Durable temporal-holdout gate for shadow pattern intake."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.core.measurement.pattern_growth import (
    HoldoutDecision,
    HoldoutOutcome,
    OutcomeRecord,
    PatternCandidate,
    PatternValidationSample,
    TemporalHoldoutValidator,
)
from fdai.core.measurement.runners import PatternBuilder
from fdai.core.tiers.t1_lightweight.tier import LearnedAction
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.state_store import StateStore

_STATE_PREFIX = "measurement:pattern_holdout:"
_MAX_SAMPLES = 1_000


@dataclass(frozen=True, slots=True)
class TemporalHoldoutEvidence:
    """One complete or incomplete durable holdout envelope."""

    pattern_id: str
    complete: bool
    samples: tuple[PatternValidationSample, ...]


class TemporalHoldoutEvidenceSource(Protocol):
    async def evidence_for(self, pattern_id: str) -> TemporalHoldoutEvidence: ...


class StateStoreTemporalHoldoutEvidenceSource:
    """Read one bounded holdout envelope from the tracked state store."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def evidence_for(self, pattern_id: str) -> TemporalHoldoutEvidence:
        value = await self._store.read_state(f"{_STATE_PREFIX}{pattern_id}")
        if value is None:
            return TemporalHoldoutEvidence(pattern_id=pattern_id, complete=False, samples=())
        return _parse_evidence(value, expected_pattern_id=pattern_id)


class HoldoutVerifiedPatternBuilder:
    """Return a candidate only after complete temporal holdout passes."""

    def __init__(
        self,
        *,
        delegate: PatternBuilder,
        evidence_source: TemporalHoldoutEvidenceSource,
        validator: TemporalHoldoutValidator,
        audit_store: StateStore,
    ) -> None:
        self._delegate = delegate
        self._evidence_source = evidence_source
        self._validator = validator
        self._audit_store = audit_store

    async def build(
        self,
        record: OutcomeRecord,
    ) -> tuple[Sequence[float], LearnedAction] | None:
        built = await self._delegate.build(record)
        if built is None:
            return None
        vector, action = built
        try:
            evidence = await self._evidence_source.evidence_for(action.signature)
        except (TypeError, ValueError):
            decision = HoldoutDecision(
                pattern_id=action.signature,
                outcome=HoldoutOutcome.INSUFFICIENT_DATA,
                observed_fp_rate=0.0,
                sample_size=0,
            )
            await self._audit(
                record=record,
                decision=decision,
                complete=False,
                reason="holdout_evidence_invalid",
            )
            return None
        if not evidence.complete:
            decision = HoldoutDecision(
                pattern_id=action.signature,
                outcome=HoldoutOutcome.INSUFFICIENT_DATA,
                observed_fp_rate=0.0,
                sample_size=len(evidence.samples),
            )
            await self._audit(
                record=record,
                decision=decision,
                complete=False,
                reason="holdout_evidence_incomplete",
            )
            return None
        decision = self._validator.evaluate(
            candidate=PatternCandidate(
                pattern_id=action.signature,
                action_type_id=record.action_type_id,
                learned_at=record.observed_at,
            ),
            holdout=evidence.samples,
        )
        await self._audit(record=record, decision=decision, complete=True, reason=None)
        if decision.outcome is not HoldoutOutcome.PASS:
            return None
        return vector, action

    async def _audit(
        self,
        *,
        record: OutcomeRecord,
        decision: HoldoutDecision,
        complete: bool,
        reason: str | None,
    ) -> None:
        await self._audit_store.append_audit_entry(
            {
                "actor": "fdai.delivery.measurement.holdout",
                "action_kind": "measurement.pattern_growth.holdout",
                "mode": Mode.SHADOW.value,
                "action_id": record.action_id,
                "action_type_id": record.action_type_id,
                "pattern_id": decision.pattern_id,
                "evidence_complete": complete,
                "outcome": decision.outcome.value,
                "reason": reason,
                "sample_size": decision.sample_size,
                "observed_fp_rate": decision.observed_fp_rate,
                "promotion_authority": False,
                "execution_authority": False,
                "recorded_at": record.observed_at.isoformat(),
            }
        )


def _parse_evidence(
    value: Mapping[str, object],
    *,
    expected_pattern_id: str,
) -> TemporalHoldoutEvidence:
    pattern_id = _text(value, "pattern_id")
    if pattern_id != expected_pattern_id:
        raise ValueError("temporal holdout pattern_id does not match its state key")
    complete = value.get("complete")
    if not isinstance(complete, bool):
        raise ValueError("temporal holdout complete MUST be a boolean")
    raw_samples = value.get("samples")
    if not isinstance(raw_samples, list) or len(raw_samples) > _MAX_SAMPLES:
        raise ValueError("temporal holdout samples MUST be a bounded array")
    samples: list[PatternValidationSample] = []
    for raw in raw_samples:
        if not isinstance(raw, Mapping):
            raise ValueError("temporal holdout sample MUST be an object")
        observed_at = _datetime(raw, "observed_at")
        was_correct = raw.get("was_correct")
        if not isinstance(was_correct, bool):
            raise ValueError("temporal holdout was_correct MUST be a boolean")
        sample_pattern_id = _text(raw, "pattern_id")
        if sample_pattern_id != pattern_id:
            raise ValueError("temporal holdout sample pattern_id does not match its envelope")
        samples.append(
            PatternValidationSample(
                pattern_id=sample_pattern_id,
                observed_at=observed_at,
                was_correct=was_correct,
            )
        )
    return TemporalHoldoutEvidence(
        pattern_id=pattern_id,
        complete=complete,
        samples=tuple(samples),
    )


def _text(value: Mapping[str, object], name: str) -> str:
    resolved = value.get(name)
    if not isinstance(resolved, str) or not resolved.strip():
        raise ValueError(f"temporal holdout {name} MUST be non-empty")
    return resolved


def _datetime(value: Mapping[str, object], name: str) -> datetime:
    raw = _text(value, name)
    try:
        resolved = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"temporal holdout {name} MUST be RFC 3339") from exc
    if resolved.tzinfo is None:
        raise ValueError(f"temporal holdout {name} MUST be timezone-aware")
    return resolved


__all__ = [
    "HoldoutVerifiedPatternBuilder",
    "StateStoreTemporalHoldoutEvidenceSource",
    "TemporalHoldoutEvidence",
    "TemporalHoldoutEvidenceSource",
]
