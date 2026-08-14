"""Deterministic admission policy for optional conversational T2 synthesis."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

_IDENTITY_FIELDS = ("resource_id", "scope_ref", "id", "correlation_id")
_CONCLUSION_FIELDS = (
    "state",
    "status",
    "verdict",
    "mode",
    "health",
    "outcome",
    "recommendation",
)
_MAX_CANONICAL_BYTES = 2_048


@dataclass(frozen=True, slots=True)
class DeliberationSignal:
    """One value-free comparison signal extracted from owned T1 facts."""

    identity_digest: str
    field: str
    value_digest: str

    def __post_init__(self) -> None:
        if self.field not in _CONCLUSION_FIELDS:
            raise ValueError("deliberation signal field is not comparable")
        if not _is_sha256(self.identity_digest) or not _is_sha256(self.value_digest):
            raise ValueError("deliberation signal digests MUST be SHA-256")


@dataclass(frozen=True, slots=True)
class T1AnswerConflict:
    """One same-identity T1 conflict without the compared values."""

    identity_digest: str
    field: str
    left_agent: str
    right_agent: str


@dataclass(frozen=True, slots=True)
class T1AnswerEvaluation:
    """Bounded deterministic decision that controls T2 admission."""

    reason: str
    signal_count: int
    conflicts: tuple[T1AnswerConflict, ...] = ()

    @property
    def requires_t2(self) -> bool:
        return bool(self.conflicts)

    def to_mapping(self) -> dict[str, object]:
        return {
            "status": "escalation_required" if self.requires_t2 else "not_required",
            "reason": self.reason,
            "signal_count": self.signal_count,
            "conflicts": [
                {
                    "field": conflict.field,
                    "left_agent": conflict.left_agent,
                    "right_agent": conflict.right_agent,
                }
                for conflict in self.conflicts
            ],
        }


class _EvaluatedClaim(Protocol):
    @property
    def agent(self) -> str: ...

    @property
    def evaluation_signals(self) -> tuple[DeliberationSignal, ...]: ...


def evaluation_signals(facts: object) -> tuple[DeliberationSignal, ...]:
    """Extract bounded comparable digests from one normalized T1 fact mapping."""

    if not isinstance(facts, Mapping):
        return ()
    identity = next(
        (
            (field, canonical)
            for field in _IDENTITY_FIELDS
            if (canonical := _canonical_scalar(facts.get(field))) is not None
        ),
        None,
    )
    if identity is None:
        return ()
    identity_field, identity_value = identity
    identity_digest = _digest(f"{identity_field}\0{identity_value}")
    return tuple(
        DeliberationSignal(
            identity_digest=identity_digest,
            field=field,
            value_digest=_digest(canonical),
        )
        for field in _CONCLUSION_FIELDS
        if (canonical := _canonical_scalar(facts.get(field))) is not None
    )


def evaluate_t1_answers(claims: Sequence[_EvaluatedClaim]) -> T1AnswerEvaluation:
    """Require T2 only for a verified same-identity structured conflict."""

    seen: dict[tuple[str, str], tuple[str, str]] = {}
    conflicts: list[T1AnswerConflict] = []
    signal_count = 0
    for claim in claims:
        for signal in claim.evaluation_signals:
            signal_count += 1
            key = (signal.identity_digest, signal.field)
            previous = seen.get(key)
            if previous is None:
                seen[key] = (claim.agent, signal.value_digest)
                continue
            previous_agent, previous_value = previous
            if previous_value == signal.value_digest or previous_agent == claim.agent:
                continue
            conflicts.append(
                T1AnswerConflict(
                    identity_digest=signal.identity_digest,
                    field=signal.field,
                    left_agent=previous_agent,
                    right_agent=claim.agent,
                )
            )
    if conflicts:
        reason = "structured_conflict"
    elif signal_count:
        reason = "no_structured_conflict"
    else:
        reason = "no_comparable_signals"
    return T1AnswerEvaluation(
        reason=reason,
        signal_count=signal_count,
        conflicts=tuple(conflicts),
    )


def _canonical_scalar(value: object) -> str | None:
    if not isinstance(value, str | int | float | bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return rendered if len(rendered.encode("utf-8")) <= _MAX_CANONICAL_BYTES else None


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "DeliberationSignal",
    "T1AnswerEvaluation",
    "evaluate_t1_answers",
    "evaluation_signals",
]
