"""Immutable models for coordinated human-agent assignment cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from fdai.core.rbac.roles import Role
from fdai.core.stewardship.model import Duty
from fdai.core.stewardship.names import AGENT_NAME_SET

_MAX_IDENTIFIER_CHARS: Final[int] = 256
_MAX_JUSTIFICATION_CHARS: Final[int] = 2_000


class AssignmentModelError(ValueError):
    """Raised when assignment-case data violates a domain invariant."""


class AssignmentState(StrEnum):
    """Durable lifecycle states for one composite assignment case."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    OWNERSHIP_PR_OPEN = "ownership_pr_open"
    OWNERSHIP_MERGED = "ownership_merged"
    IAM_APPLYING = "iam_applying"
    ACTIVE = "active"
    REJECTED = "rejected"
    DEGRADED = "degraded"
    SUPERSEDED = "superseded"


class ReviewDecision(StrEnum):
    """Independent human review outcomes."""

    APPROVE = "approve"
    REJECT = "reject"


class EffectKind(StrEnum):
    """Independent effects that must converge before activation."""

    OWNERSHIP = "ownership"
    IAM = "iam"


@dataclass(frozen=True, slots=True)
class ProviderSubject:
    """Stable identity-provider subject selected for assignment."""

    provider: str
    subject_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _identifier(self.provider, "provider").casefold())
        object.__setattr__(self, "subject_id", _identifier(self.subject_id, "subject_id"))

    def to_dict(self) -> dict[str, str]:
        return {"provider": self.provider, "subject_id": self.subject_id}


@dataclass(frozen=True, slots=True)
class DutyBinding:
    """One operational duty assigned to the target subject."""

    agent_name: str
    duty: Duty
    scope_ref: str

    def __post_init__(self) -> None:
        if self.agent_name not in AGENT_NAME_SET:
            raise AssignmentModelError(f"unknown pantheon agent: {self.agent_name}")
        object.__setattr__(self, "scope_ref", _identifier(self.scope_ref, "scope_ref"))

    def to_dict(self) -> dict[str, str]:
        return {
            "agent_name": self.agent_name,
            "duty": self.duty.value,
            "scope_ref": self.scope_ref,
        }


@dataclass(frozen=True, slots=True)
class AssignmentIntent:
    """Immutable requested role, duties, goals, and attribution."""

    idempotency_key: str
    subject: ProviderSubject
    requested_role: Role
    duty_bindings: tuple[DutyBinding, ...]
    goal_refs: tuple[str, ...]
    requester_ref: str
    justification: str

    def __post_init__(self) -> None:
        if self.requested_role is Role.BREAK_GLASS:
            raise AssignmentModelError("BreakGlass is not available for routine assignment")
        if not self.duty_bindings:
            raise AssignmentModelError("at least one duty binding is required")
        object.__setattr__(
            self,
            "idempotency_key",
            _identifier(self.idempotency_key, "idempotency_key"),
        )
        object.__setattr__(self, "requester_ref", _identifier(self.requester_ref, "requester_ref"))
        object.__setattr__(self, "duty_bindings", tuple(self.duty_bindings))
        normalized_goals = tuple(_identifier(ref, "goal_ref") for ref in self.goal_refs)
        if len(set(normalized_goals)) != len(normalized_goals):
            raise AssignmentModelError("goal refs MUST be unique")
        object.__setattr__(self, "goal_refs", normalized_goals)
        justification = self.justification.strip()
        if not justification:
            raise AssignmentModelError("justification MUST be non-empty")
        if len(justification) > _MAX_JUSTIFICATION_CHARS:
            raise AssignmentModelError(
                f"justification MUST be at most {_MAX_JUSTIFICATION_CHARS} characters"
            )
        object.__setattr__(self, "justification", justification)

    def to_dict(self) -> dict[str, Any]:
        return {
            "idempotency_key": self.idempotency_key,
            "subject": self.subject.to_dict(),
            "requested_role": self.requested_role.value,
            "duty_bindings": [binding.to_dict() for binding in self.duty_bindings],
            "goal_refs": list(self.goal_refs),
            "requester_ref": self.requester_ref,
            "justification": self.justification,
        }


@dataclass(frozen=True, slots=True)
class ReviewReceipt:
    """Content-free proof of one independent review decision."""

    reviewer_ref: str
    decision: ReviewDecision
    reviewed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "reviewer_ref", _identifier(self.reviewer_ref, "reviewer_ref"))
        _aware(self.reviewed_at, "reviewed_at")

    def to_dict(self) -> dict[str, str]:
        return {
            "reviewer_ref": self.reviewer_ref,
            "decision": self.decision.value,
            "reviewed_at": self.reviewed_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class EffectReceipt:
    """Content-addressed proof that one independent effect converged."""

    kind: EffectKind
    receipt_ref: str
    digest: str
    received_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_ref", _identifier(self.receipt_ref, "receipt_ref"))
        object.__setattr__(self, "digest", _identifier(self.digest, "digest"))
        _aware(self.received_at, "received_at")

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "receipt_ref": self.receipt_ref,
            "digest": self.digest,
            "received_at": self.received_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class AssignmentCase:
    """Immutable snapshot of assignment intent and revisioned lifecycle state."""

    case_id: str
    intent: AssignmentIntent
    state: AssignmentState = AssignmentState.DRAFT
    revision: int = 1
    reviews: tuple[ReviewReceipt, ...] = ()
    effect_receipts: tuple[EffectReceipt, ...] = ()
    degraded_reason: str | None = None
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _identifier(self.case_id, "case_id"))
        if self.revision < 1:
            raise AssignmentModelError("revision MUST be >= 1")
        object.__setattr__(self, "reviews", tuple(self.reviews))
        object.__setattr__(self, "effect_receipts", tuple(self.effect_receipts))
        reviewers = [receipt.reviewer_ref.strip().casefold() for receipt in self.reviews]
        if len(set(reviewers)) != len(reviewers):
            raise AssignmentModelError("reviewers MUST be distinct after normalization")
        effect_kinds = [receipt.kind for receipt in self.effect_receipts]
        if len(set(effect_kinds)) != len(effect_kinds):
            raise AssignmentModelError("effect receipt kinds MUST be unique")
        if self.state is AssignmentState.ACTIVE and not self.has_required_effects:
            raise AssignmentModelError(
                "active assignment requires ownership and IAM effect receipts"
            )
        if self.degraded_reason is not None:
            object.__setattr__(
                self,
                "degraded_reason",
                _identifier(self.degraded_reason, "degraded_reason"),
            )
        if self.superseded_by is not None:
            object.__setattr__(
                self,
                "superseded_by",
                _identifier(self.superseded_by, "superseded_by"),
            )

    @property
    def effect_kinds(self) -> frozenset[EffectKind]:
        return frozenset(receipt.kind for receipt in self.effect_receipts)

    @property
    def has_required_effects(self) -> bool:
        return self.effect_kinds == frozenset({EffectKind.OWNERSHIP, EffectKind.IAM})

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "intent": self.intent.to_dict(),
            "state": self.state.value,
            "revision": self.revision,
            "reviews": [review.to_dict() for review in self.reviews],
            "effect_receipts": [receipt.to_dict() for receipt in self.effect_receipts],
            "degraded_reason": self.degraded_reason,
            "superseded_by": self.superseded_by,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AssignmentCase:
        raw_intent = _mapping(value, "intent")
        raw_subject = _mapping(raw_intent, "subject")
        intent = AssignmentIntent(
            idempotency_key=_string(raw_intent, "idempotency_key"),
            subject=ProviderSubject(
                provider=_string(raw_subject, "provider"),
                subject_id=_string(raw_subject, "subject_id"),
            ),
            requested_role=Role(_string(raw_intent, "requested_role")),
            duty_bindings=tuple(
                DutyBinding(
                    agent_name=_string(item, "agent_name"),
                    duty=Duty(_string(item, "duty")),
                    scope_ref=_string(item, "scope_ref"),
                )
                for item in _mapping_list(raw_intent, "duty_bindings")
            ),
            goal_refs=tuple(
                _string_value(item, "goal_ref") for item in _string_list(raw_intent, "goal_refs")
            ),
            requester_ref=_string(raw_intent, "requester_ref"),
            justification=_string(raw_intent, "justification"),
        )
        return cls(
            case_id=_string(value, "case_id"),
            intent=intent,
            state=AssignmentState(_string(value, "state")),
            revision=_integer(value, "revision"),
            reviews=tuple(
                ReviewReceipt(
                    reviewer_ref=_string(item, "reviewer_ref"),
                    decision=ReviewDecision(_string(item, "decision")),
                    reviewed_at=datetime.fromisoformat(_string(item, "reviewed_at")),
                )
                for item in _mapping_list(value, "reviews")
            ),
            effect_receipts=tuple(
                EffectReceipt(
                    kind=EffectKind(_string(item, "kind")),
                    receipt_ref=_string(item, "receipt_ref"),
                    digest=_string(item, "digest"),
                    received_at=datetime.fromisoformat(_string(item, "received_at")),
                )
                for item in _mapping_list(value, "effect_receipts")
            ),
            degraded_reason=_optional_string(value, "degraded_reason"),
            superseded_by=_optional_string(value, "superseded_by"),
        )


def _identifier(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise AssignmentModelError(f"{name} MUST be non-empty")
    if len(normalized) > _MAX_IDENTIFIER_CHARS:
        raise AssignmentModelError(f"{name} MUST be at most {_MAX_IDENTIFIER_CHARS} characters")
    return normalized


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise AssignmentModelError(f"{name} MUST be timezone-aware")


def _mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise AssignmentModelError(f"stored assignment {key} MUST be an object")
    return item


def _mapping_list(value: dict[str, Any], key: str) -> tuple[dict[str, Any], ...]:
    items = value.get(key)
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise AssignmentModelError(f"stored assignment {key} MUST be an object list")
    return tuple(items)


def _string_list(value: dict[str, Any], key: str) -> tuple[str, ...]:
    items = value.get(key)
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise AssignmentModelError(f"stored assignment {key} MUST be a string list")
    return tuple(items)


def _string(value: dict[str, Any], key: str) -> str:
    return _string_value(value.get(key), key)


def _string_value(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise AssignmentModelError(f"stored assignment {name} MUST be a string")
    return value


def _optional_string(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    return _string_value(item, key)


def _integer(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int):
        raise AssignmentModelError(f"stored assignment {key} MUST be an integer")
    return item


__all__ = [
    "AssignmentCase",
    "AssignmentIntent",
    "AssignmentModelError",
    "AssignmentState",
    "DutyBinding",
    "EffectKind",
    "EffectReceipt",
    "ProviderSubject",
    "ReviewDecision",
    "ReviewReceipt",
]
