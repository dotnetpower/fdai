"""Inert automation blueprint candidate and evidence contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.core.scheduler.models import ScheduledRunIsolationProfile

_SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,255}$")


class BlueprintEvidenceSource(StrEnum):
    OPERATOR_TURN = "operator_turn"
    SCHEDULED_RUN = "scheduled_run"
    BLUEPRINT_REVIEW = "blueprint_review"


class BlueprintOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AutomationBlueprintState(StrEnum):
    DRAFT = "draft"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    MATERIALIZED = "materialized"


@dataclass(frozen=True, slots=True)
class AutomationBlueprintEvidence:
    evidence_id: str
    principal_id: str
    normalized_task_intent: str
    schedule_class: str
    schedule_expression: str
    event_type: str
    resource_scope: str
    delivery_intent: str
    required_tools: tuple[str, ...]
    isolation_profile: ScheduledRunIsolationProfile
    outcome: BlueprintOutcome
    source: BlueprintEvidenceSource
    occurred_at: datetime
    estimated_cost_microusd: int = 0
    unresolved_failure: bool = False

    def __post_init__(self) -> None:
        for label, value in (
            ("evidence_id", self.evidence_id),
            ("principal_id", self.principal_id),
            ("event_type", self.event_type),
            ("resource_scope", self.resource_scope),
            ("delivery_intent", self.delivery_intent),
        ):
            if _SAFE_ID.fullmatch(value) is None:
                raise ValueError(f"blueprint evidence {label} MUST be a bounded safe identifier")
        _bounded_text("normalized_task_intent", self.normalized_task_intent, 512)
        _bounded_text("schedule_class", self.schedule_class, 64)
        _bounded_text("schedule_expression", self.schedule_expression, 128)
        if len(set(self.required_tools)) != len(self.required_tools):
            raise ValueError("blueprint evidence required_tools MUST NOT contain duplicates")
        if any(_SAFE_ID.fullmatch(tool) is None for tool in self.required_tools):
            raise ValueError("blueprint evidence required_tools MUST be safe identifiers")
        if self.occurred_at.tzinfo is None:
            raise ValueError("blueprint evidence occurred_at MUST include timezone")
        if self.estimated_cost_microusd < 0:
            raise ValueError("blueprint evidence cost MUST be non-negative")

    @property
    def dedup_key(self) -> str:
        return _digest(
            {
                "intent": self.normalized_task_intent,
                "principal": self.principal_id,
                "resource_scope": self.resource_scope,
                "schedule_class": self.schedule_class,
            }
        )

    @property
    def fingerprint(self) -> str:
        return _digest(
            {
                "dedup_key": self.dedup_key,
                "delivery_intent": self.delivery_intent,
                "event_type": self.event_type,
                "evidence_id": self.evidence_id,
                "isolation_profile": self.isolation_profile.profile_id,
                "required_tools": sorted(self.required_tools),
                "schedule_expression": self.schedule_expression,
            }
        )


@dataclass(frozen=True, slots=True)
class AutomationBlueprintCandidate:
    candidate_id: str
    dedup_key: str
    normalized_task_intent: str
    schedule_class: str
    schedule_expression: str
    event_type: str
    principal_id: str
    resource_scope: str
    delivery_intent: str
    required_tools: tuple[str, ...]
    isolation_profile: ScheduledRunIsolationProfile
    estimated_cost_microusd: int
    evidence_fingerprints: tuple[str, ...]
    proposer: str
    confidence: float
    created_at: datetime
    expires_at: datetime
    state: AutomationBlueprintState = AutomationBlueprintState.DRAFT
    enabled: bool = False
    shadow_only: bool = True
    mutation_tool_ids: tuple[str, ...] = ()
    reviewed_by: str | None = None
    review_reason: str | None = None
    resulting_task_id: str | None = None
    realized_usage_count: int = 0

    def __post_init__(self) -> None:
        if _SAFE_ID.fullmatch(self.candidate_id) is None:
            raise ValueError("blueprint candidate_id MUST be a bounded safe identifier")
        if not 0 <= self.confidence <= 1:
            raise ValueError("blueprint confidence MUST be in [0, 1]")
        if not self.evidence_fingerprints:
            raise ValueError("blueprint candidate MUST cite evidence fingerprints")
        if len(set(self.evidence_fingerprints)) != len(self.evidence_fingerprints):
            raise ValueError("blueprint evidence fingerprints MUST be unique")
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("blueprint timestamps MUST include timezone")
        if self.expires_at <= self.created_at:
            raise ValueError("blueprint expiry MUST follow creation")
        if self.enabled or not self.shadow_only or self.mutation_tool_ids:
            raise ValueError(
                "blueprint candidates MUST be disabled shadow-only with zero mutation tools"
            )
        if self.state is AutomationBlueprintState.MATERIALIZED and not self.resulting_task_id:
            raise ValueError("materialized blueprint MUST record the resulting task id")
        if self.realized_usage_count < 0:
            raise ValueError("blueprint realized usage count MUST be non-negative")


def _bounded_text(label: str, value: str, maximum: int) -> None:
    if not value.strip() or len(value) > maximum or any(ord(character) < 32 for character in value):
        raise ValueError(f"blueprint evidence {label} MUST be bounded printable text")


def _digest(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AutomationBlueprintCandidate",
    "AutomationBlueprintEvidence",
    "AutomationBlueprintState",
    "BlueprintEvidenceSource",
    "BlueprintOutcome",
]
