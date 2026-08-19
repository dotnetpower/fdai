"""Mechanical schedule profile and due gate for read-only question campaigns."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from fdai.core.conversation.question_perspectives import QuestionPerspective

_PROFILE_ID_PATTERN = re.compile(r"[a-z][a-z0-9.-]{0,95}")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class QuestionScheduleProfile:
    """Bounded schedule, model profile reference, and shadow campaign budgets."""

    profile_id: str
    cron: str
    generation_profile: str
    model_profile: str
    question_budget: int
    time_budget_seconds: int
    no_progress_seconds: int
    token_budget: int
    cost_budget_microusd: int
    locales: tuple[str, ...]
    perspectives: tuple[QuestionPerspective, ...]
    enabled: bool = False
    timezone: str = "UTC"
    mode: str = "shadow"

    def __post_init__(self) -> None:
        if _PROFILE_ID_PATTERN.fullmatch(self.profile_id) is None:
            raise ValueError("question schedule profile_id MUST be a bounded identifier")
        if len(self.cron.split()) != 5 or not croniter.is_valid(self.cron, strict=True):
            raise ValueError("question schedule cron MUST be a strict 5-field expression")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("question schedule timezone MUST be a valid IANA timezone") from error
        if not self.generation_profile or not self.model_profile:
            raise ValueError("question schedule generation and model profiles MUST be non-empty")
        if not 1 <= self.question_budget <= 100:
            raise ValueError("question schedule budget MUST be in [1, 100]")
        if not 1 <= self.no_progress_seconds <= self.time_budget_seconds <= 86_400:
            raise ValueError("question schedule time and no-progress budgets are inconsistent")
        if self.token_budget < 1 or self.cost_budget_microusd < 1:
            raise ValueError("question schedule token and cost budgets MUST be positive")
        if self.locales != tuple(sorted(set(self.locales))) or not self.locales:
            raise ValueError("question schedule locales MUST be non-empty, unique, and ordered")
        if any(locale not in {"en", "ko"} for locale in self.locales):
            raise ValueError("question schedule locales MUST be en or ko")
        if (
            self.perspectives != tuple(sorted(set(self.perspectives), key=lambda item: item.value))
            or not self.perspectives
        ):
            raise ValueError(
                "question schedule perspectives MUST be non-empty, unique, and ordered"
            )
        if self.mode != "shadow":
            raise ValueError("question schedule mode MUST remain shadow")


@dataclass(frozen=True, slots=True)
class QuestionWorkloadPrincipalReceipt:
    """Authenticated workload identity and server-owned Reader mapping evidence."""

    principal_digest: str
    role: str
    role_source: str
    scope_digest: str
    purpose: str
    authentication_evidence_digest: str
    authenticated_at: datetime
    expires_at: datetime
    principal_kind: str = "workload"

    def __post_init__(self) -> None:
        for value in (
            self.principal_digest,
            self.scope_digest,
            self.authentication_evidence_digest,
        ):
            if _DIGEST_PATTERN.fullmatch(value) is None:
                raise ValueError("question workload principal digests MUST be canonical")
        if self.principal_kind != "workload":
            raise ValueError("question campaign principal MUST be a workload identity")
        if not self.role or not self.role_source or len(self.role_source) > 128:
            raise ValueError("question workload role mapping MUST be bounded")
        if not self.purpose or len(self.purpose) > 128:
            raise ValueError("question workload purpose MUST be bounded")
        if self.authenticated_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("question workload authentication times MUST be timezone-aware")
        if self.expires_at <= self.authenticated_at:
            raise ValueError("question workload authentication MUST expire after issuance")


@dataclass(frozen=True, slots=True)
class QuestionCampaignPrerequisites:
    """Measured readiness inputs that can only block one scheduled run."""

    previous_campaign_terminal: bool
    ontology_available: bool
    manifest_available: bool
    semantic_transport_ready: bool
    workload_principal: QuestionWorkloadPrincipalReceipt | None
    generation_model_available: bool
    evidence_minimum_ready: bool
    budget_remaining: bool
    campaign_lock_available: bool


@dataclass(frozen=True, slots=True)
class QuestionCampaignDueDecision:
    """Due, skipped, or held result produced before model or provider work."""

    state: str
    reason: str
    due: bool
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.state not in {"due", "skipped", "held"}:
            raise ValueError("question campaign due state is invalid")
        if self.due != (self.state == "due"):
            raise ValueError("question campaign due flag does not match its state")
        if self.execution_authority:
            raise ValueError("question campaign due decision has no execution authority")


def evaluate_question_campaign_due(
    *,
    profile: QuestionScheduleProfile,
    prerequisites: QuestionCampaignPrerequisites,
    now: datetime,
    last_started_at: datetime | None,
) -> QuestionCampaignDueDecision:
    """Evaluate schedule and readiness without calling a model or semantic runtime."""

    if now.tzinfo is None:
        raise ValueError("question campaign due time MUST be timezone-aware")
    if last_started_at is not None and last_started_at.tzinfo is None:
        raise ValueError("question campaign last start MUST be timezone-aware")
    if not profile.enabled:
        return _decision("skipped", "schedule_disabled")
    local_now = now.astimezone(ZoneInfo(profile.timezone))
    if not croniter.match(profile.cron, local_now):
        return _decision("skipped", "schedule_not_due")
    if last_started_at is not None:
        local_last = last_started_at.astimezone(ZoneInfo(profile.timezone))
        if local_last.replace(second=0, microsecond=0) == local_now.replace(
            second=0, microsecond=0
        ):
            return _decision("skipped", "schedule_already_started")
    principal = prerequisites.workload_principal
    gates = (
        (prerequisites.previous_campaign_terminal, "previous_campaign_active"),
        (prerequisites.ontology_available, "ontology_unavailable"),
        (prerequisites.manifest_available, "principal_manifest_unavailable"),
        (prerequisites.semantic_transport_ready, "semantic_transport_unavailable"),
        (principal is not None, "scheduled_principal_unavailable"),
        (
            principal is not None
            and principal.expires_at > now
            and principal.role == "reader"
            and principal.purpose == "operations-review",
            "scheduled_principal_reader_mapping_unavailable",
        ),
        (prerequisites.generation_model_available, "generation_model_unavailable"),
        (prerequisites.evidence_minimum_ready, "evidence_minimum_unavailable"),
        (prerequisites.budget_remaining, "campaign_budget_exhausted"),
        (prerequisites.campaign_lock_available, "campaign_lock_unavailable"),
    )
    for ready, reason in gates:
        if not ready:
            return _decision("held", reason)
    return _decision("due", "campaign_due")


def _decision(state: str, reason: str) -> QuestionCampaignDueDecision:
    return QuestionCampaignDueDecision(state=state, reason=reason, due=state == "due")


__all__ = [
    "QuestionCampaignDueDecision",
    "QuestionCampaignPrerequisites",
    "QuestionScheduleProfile",
    "QuestionWorkloadPrincipalReceipt",
    "evaluate_question_campaign_due",
]
