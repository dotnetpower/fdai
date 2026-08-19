"""Proof-carrying bounded question campaign contracts and evaluation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from fdai.core.conversation.epistemic_coverage import EpistemicQuestionRecord, EpistemicStatus
from fdai.core.conversation_assurance.models import TurnAssessmentInput

_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_SOURCE_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")
_CAMPAIGN_ID_PATTERN = re.compile(r"qs:[0-9a-f]{64}")
_TERMINAL_DISPOSITIONS = frozenset(
    {"answered", "clarification", "held", "unsupported", "action_draft", "cancelled"}
)
_MAX_QUESTIONS = 100
_MAX_ATTEMPTS = 10


class QuestionCampaignTrigger(StrEnum):
    """Authority-neutral source that started a bounded campaign."""

    MANUAL = "manual"
    SCHEDULED = "scheduled"
    RELEASE_CERTIFICATION = "release_certification"


class QuestionCampaignState(StrEnum):
    """Terminal or active campaign lifecycle state."""

    RUNNING = "running"
    COMPLETED = "completed"
    HELD = "held"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class QuestionCampaignIdentity:
    """Immutable source, semantic, principal, model, scope, and budget binding."""

    campaign_id: str
    source_revision: str
    ontology_release_digest: str
    principal_manifest_digests: tuple[str, ...]
    question_universe_digest: str
    generation_profile_digest: str
    model_set_digest: str
    scope_digest: str
    started_at: datetime
    question_budget: int
    time_budget_seconds: int
    no_progress_seconds: int
    token_budget: int
    cost_budget_microusd: int
    trigger: QuestionCampaignTrigger
    mode: str = "shadow"

    def __post_init__(self) -> None:
        if _CAMPAIGN_ID_PATTERN.fullmatch(self.campaign_id) is None:
            raise ValueError("question campaign id MUST be content-addressed")
        if _SOURCE_REVISION_PATTERN.fullmatch(self.source_revision) is None:
            raise ValueError("question campaign source revision MUST be a Git SHA-1")
        for value in (
            self.ontology_release_digest,
            self.question_universe_digest,
            self.generation_profile_digest,
            self.model_set_digest,
            self.scope_digest,
        ):
            _require_digest("question campaign digest", value)
        if (
            self.principal_manifest_digests != tuple(sorted(set(self.principal_manifest_digests)))
            or not self.principal_manifest_digests
        ):
            raise ValueError("question campaign principal manifests MUST be non-empty and ordered")
        for value in self.principal_manifest_digests:
            _require_digest("question campaign principal manifest", value)
        if self.started_at.tzinfo is None:
            raise ValueError("question campaign start time MUST be timezone-aware")
        if not 1 <= self.question_budget <= _MAX_QUESTIONS:
            raise ValueError(f"question campaign budget MUST be in [1, {_MAX_QUESTIONS}]")
        if not 1 <= self.no_progress_seconds <= self.time_budget_seconds <= 86_400:
            raise ValueError("question campaign time and no-progress budgets are inconsistent")
        if self.token_budget < 0 or self.cost_budget_microusd < 0:
            raise ValueError("question campaign token and cost budgets MUST be non-negative")
        if self.trigger is QuestionCampaignTrigger.SCHEDULED and (
            self.token_budget == 0 or self.cost_budget_microusd == 0
        ):
            raise ValueError("scheduled question campaign requires positive token and cost budgets")
        if self.mode != "shadow":
            raise ValueError("question campaigns MUST remain shadow")


def build_question_campaign_identity(
    *,
    source_revision: str,
    ontology_release_digest: str,
    principal_manifest_digests: Sequence[str],
    question_universe_digest: str,
    generation_profile_digest: str,
    model_set_digest: str,
    scope_digest: str,
    started_at: datetime,
    question_budget: int,
    time_budget_seconds: int,
    no_progress_seconds: int,
    token_budget: int,
    cost_budget_microusd: int,
    trigger: QuestionCampaignTrigger,
) -> QuestionCampaignIdentity:
    """Build a replay-stable campaign id from every immutable identity axis."""

    body = {
        "source_revision": source_revision,
        "ontology_release_digest": ontology_release_digest,
        "principal_manifest_digests": tuple(sorted(set(principal_manifest_digests))),
        "question_universe_digest": question_universe_digest,
        "generation_profile_digest": generation_profile_digest,
        "model_set_digest": model_set_digest,
        "scope_digest": scope_digest,
        "started_at": started_at.isoformat(),
        "question_budget": question_budget,
        "time_budget_seconds": time_budget_seconds,
        "no_progress_seconds": no_progress_seconds,
        "token_budget": token_budget,
        "cost_budget_microusd": cost_budget_microusd,
        "trigger": trigger.value,
        "mode": "shadow",
    }
    return QuestionCampaignIdentity(
        campaign_id=f"qs:{_digest(body).removeprefix('sha256:')}",
        source_revision=source_revision,
        ontology_release_digest=ontology_release_digest,
        principal_manifest_digests=tuple(sorted(set(principal_manifest_digests))),
        question_universe_digest=question_universe_digest,
        generation_profile_digest=generation_profile_digest,
        model_set_digest=model_set_digest,
        scope_digest=scope_digest,
        started_at=started_at,
        question_budget=question_budget,
        time_budget_seconds=time_budget_seconds,
        no_progress_seconds=no_progress_seconds,
        token_budget=token_budget,
        cost_budget_microusd=cost_budget_microusd,
        trigger=trigger,
    )


@dataclass(frozen=True, slots=True)
class QuestionCampaignHardZeroCounters:
    """Violation counters that block campaign release evidence above zero."""

    unsupported_claim_count: int = 0
    unauthorized_execution_count: int = 0
    hidden_scope_leak_count: int = 0
    unsafe_mutation_survivor_count: int = 0
    locale_divergence_count: int = 0
    rule_state_confusion_count: int = 0
    unverified_impact_promotion_count: int = 0
    truncation_concealment_count: int = 0

    def __post_init__(self) -> None:
        if any(value < 0 for value in asdict(self).values()):
            raise ValueError("question campaign hard-zero counters MUST be non-negative")

    @property
    def total(self) -> int:
        """Return the exact release-blocking violation total."""

        return sum(asdict(self).values())


@dataclass(frozen=True, slots=True)
class QuestionCaseAttemptRecord:
    """Bounded join from one validated question to assurance and epistemic proof."""

    campaign_id: str
    case_id: str
    validated_question_digest: str
    semantic_turn_id: str
    attempt_number: int
    terminal_disposition: str | None
    terminal_reason: str | None
    failure_kind: str | None
    assessment_id: str | None
    epistemic_record_digest: str | None
    latency_ms: int
    model_calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_microusd: int
    hard_zero: QuestionCampaignHardZeroCounters = QuestionCampaignHardZeroCounters()
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if _CAMPAIGN_ID_PATTERN.fullmatch(self.campaign_id) is None:
            raise ValueError("question attempt campaign id is invalid")
        if not self.case_id or not self.semantic_turn_id:
            raise ValueError("question attempt identities MUST be non-empty")
        _require_digest("validated question digest", self.validated_question_digest)
        if not 1 <= self.attempt_number <= _MAX_ATTEMPTS:
            raise ValueError(f"question attempt number MUST be in [1, {_MAX_ATTEMPTS}]")
        if (self.terminal_disposition is None) == (self.failure_kind is None):
            raise ValueError("question attempt requires one disposition or failure kind")
        if (self.terminal_disposition is None) != (self.terminal_reason is None):
            raise ValueError("terminal question attempt requires one typed reason")
        if self.terminal_reason is not None and (
            not self.terminal_reason or len(self.terminal_reason) > 128
        ):
            raise ValueError("question attempt terminal reason MUST be bounded")
        if self.terminal_disposition is not None and (
            self.terminal_disposition not in _TERMINAL_DISPOSITIONS
        ):
            raise ValueError("question attempt disposition is not terminal")
        if self.epistemic_record_digest is not None:
            _require_digest("epistemic record digest", self.epistemic_record_digest)
        if any(
            value < 0
            for value in (
                self.latency_ms,
                self.model_calls,
                self.prompt_tokens,
                self.completion_tokens,
                self.cost_microusd,
            )
        ):
            raise ValueError("question attempt latency and metering MUST be non-negative")
        if self.execution_authority:
            raise ValueError("question campaign attempts MUST NOT carry execution authority")


@dataclass(frozen=True, slots=True)
class QuestionCampaignEvaluationReceipt:
    """Progress or closure decision over the latest selected case attempts."""

    campaign_id: str
    question_universe_digest: str
    selected_case_count: int
    terminal_case_count: int
    full_universe_case_count: int
    hard_zero: QuestionCampaignHardZeroCounters
    subset_complete: bool
    full_universe_closed: bool
    budget_within_limit: bool
    release_evidence_eligible: bool
    receipt_digest: str


@dataclass(frozen=True, slots=True)
class QuestionCampaignCompletionRecord:
    """Immutable terminal campaign state and bounded metering aggregate."""

    campaign_id: str
    completed_at: datetime
    state: QuestionCampaignState
    reason: str
    evaluation_receipt_digest: str
    selected_case_ids_digest: str
    selected_case_count: int
    terminal_case_count: int
    full_universe_case_count: int
    model_calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_microusd: int
    hard_zero: QuestionCampaignHardZeroCounters
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if _CAMPAIGN_ID_PATTERN.fullmatch(self.campaign_id) is None:
            raise ValueError("question campaign completion id is invalid")
        if self.completed_at.tzinfo is None:
            raise ValueError("question campaign completion time MUST be timezone-aware")
        if self.state is QuestionCampaignState.RUNNING:
            raise ValueError("question campaign completion state MUST be terminal")
        if not self.reason or len(self.reason) > 128:
            raise ValueError("question campaign completion reason MUST be bounded")
        _require_digest("question campaign evaluation receipt", self.evaluation_receipt_digest)
        _require_digest("question campaign selected cases", self.selected_case_ids_digest)
        if not 0 <= self.terminal_case_count <= self.selected_case_count <= _MAX_QUESTIONS:
            raise ValueError("question campaign completion case counts are inconsistent")
        if self.full_universe_case_count < self.selected_case_count:
            raise ValueError("question campaign completion universe count is inconsistent")
        if any(
            value < 0
            for value in (
                self.model_calls,
                self.prompt_tokens,
                self.completion_tokens,
                self.cost_microusd,
            )
        ):
            raise ValueError("question campaign completion metering MUST be non-negative")
        if self.execution_authority:
            raise ValueError("question campaign completion MUST NOT carry execution authority")


def build_question_campaign_completion(
    *,
    identity: QuestionCampaignIdentity,
    completed_at: datetime,
    state: QuestionCampaignState,
    reason: str,
    evaluation: QuestionCampaignEvaluationReceipt,
    selected_case_ids: Sequence[str],
    attempts: Sequence[QuestionCaseAttemptRecord],
) -> QuestionCampaignCompletionRecord:
    """Build one terminal aggregate without copying question or answer content."""

    selected = tuple(sorted(set(selected_case_ids)))
    if len(selected) != len(selected_case_ids) or len(selected) != evaluation.selected_case_count:
        raise ValueError("question campaign completion selection is inconsistent")
    if evaluation.campaign_id != identity.campaign_id:
        raise ValueError("question campaign completion binds a different campaign")
    if any(attempt.campaign_id != identity.campaign_id for attempt in attempts):
        raise ValueError("question campaign completion attempts bind a different campaign")
    return QuestionCampaignCompletionRecord(
        campaign_id=identity.campaign_id,
        completed_at=completed_at,
        state=state,
        reason=reason,
        evaluation_receipt_digest=evaluation.receipt_digest,
        selected_case_ids_digest=_digest(selected),
        selected_case_count=evaluation.selected_case_count,
        terminal_case_count=evaluation.terminal_case_count,
        full_universe_case_count=evaluation.full_universe_case_count,
        model_calls=sum(attempt.model_calls for attempt in attempts),
        prompt_tokens=sum(attempt.prompt_tokens for attempt in attempts),
        completion_tokens=sum(attempt.completion_tokens for attempt in attempts),
        cost_microusd=sum(attempt.cost_microusd for attempt in attempts),
        hard_zero=evaluation.hard_zero,
    )


def evaluate_question_campaign(
    *,
    identity: QuestionCampaignIdentity,
    selected_case_ids: Sequence[str],
    full_universe_case_ids: Sequence[str],
    attempts: Sequence[QuestionCaseAttemptRecord],
) -> QuestionCampaignEvaluationReceipt:
    """Evaluate latest attempts while keeping partial progress distinct from closure."""

    selected = tuple(sorted(set(selected_case_ids)))
    full_universe = tuple(sorted(set(full_universe_case_ids)))
    if len(selected) != len(selected_case_ids) or not selected:
        raise ValueError("question campaign selected case ids MUST be non-empty and unique")
    if len(full_universe) != len(full_universe_case_ids) or not set(selected) <= set(full_universe):
        raise ValueError("question campaign selected cases MUST belong to the exact universe")
    if len(selected) > identity.question_budget:
        raise ValueError("question campaign selection exceeds its budget")
    latest: dict[str, QuestionCaseAttemptRecord] = {}
    seen_attempts: set[tuple[str, int]] = set()
    for attempt in attempts:
        if attempt.campaign_id != identity.campaign_id or attempt.case_id not in selected:
            raise ValueError("question attempt is outside the campaign selection")
        attempt_key = (attempt.case_id, attempt.attempt_number)
        if attempt_key in seen_attempts:
            raise ValueError("question campaign attempts MUST be unique")
        seen_attempts.add(attempt_key)
        previous = latest.get(attempt.case_id)
        if previous is None or attempt.attempt_number > previous.attempt_number:
            latest[attempt.case_id] = attempt
    terminal = tuple(
        item for item in latest.values() if item.terminal_disposition in _TERMINAL_DISPOSITIONS
    )
    hard_zero = _sum_hard_zero(terminal)
    prompt_tokens = sum(item.prompt_tokens for item in attempts)
    completion_tokens = sum(item.completion_tokens for item in attempts)
    cost_microusd = sum(item.cost_microusd for item in attempts)
    budget_within_limit = (
        identity.token_budget == 0 or prompt_tokens + completion_tokens <= identity.token_budget
    ) and (identity.cost_budget_microusd == 0 or cost_microusd <= identity.cost_budget_microusd)
    subset_complete = len(terminal) == len(selected)
    full_universe_closed = (
        subset_complete
        and selected == full_universe
        and all(item.epistemic_record_digest is not None for item in terminal)
    )
    proof_complete = all(item.epistemic_record_digest is not None for item in terminal)
    eligible = subset_complete and proof_complete and hard_zero.total == 0 and budget_within_limit
    body = {
        "campaign_id": identity.campaign_id,
        "question_universe_digest": identity.question_universe_digest,
        "selected_case_count": len(selected),
        "terminal_case_count": len(terminal),
        "full_universe_case_count": len(full_universe),
        "hard_zero": asdict(hard_zero),
        "subset_complete": subset_complete,
        "full_universe_closed": full_universe_closed,
        "budget_within_limit": budget_within_limit,
        "release_evidence_eligible": eligible,
    }
    return QuestionCampaignEvaluationReceipt(
        campaign_id=identity.campaign_id,
        question_universe_digest=identity.question_universe_digest,
        selected_case_count=len(selected),
        terminal_case_count=len(terminal),
        full_universe_case_count=len(full_universe),
        hard_zero=hard_zero,
        subset_complete=subset_complete,
        full_universe_closed=full_universe_closed,
        budget_within_limit=budget_within_limit,
        release_evidence_eligible=eligible,
        receipt_digest=_digest(body),
    )


class QuestionCampaignLedger(Protocol):
    """Append-only campaign and attempt persistence contract."""

    async def create_campaign(self, identity: QuestionCampaignIdentity) -> bool: ...

    async def append_attempt(self, record: QuestionCaseAttemptRecord) -> bool: ...

    async def get_campaign(self, campaign_id: str) -> QuestionCampaignIdentity | None: ...

    async def list_attempts(self, campaign_id: str) -> tuple[QuestionCaseAttemptRecord, ...]: ...

    async def finalize_campaign(self, record: QuestionCampaignCompletionRecord) -> bool: ...

    async def get_completion(self, campaign_id: str) -> QuestionCampaignCompletionRecord | None: ...

    async def claim_case(
        self,
        *,
        campaign_id: str,
        case_id: str,
        owner_id: str,
        claimed_at: datetime,
        lease_seconds: int,
    ) -> bool: ...

    async def release_case_claim(
        self, *, campaign_id: str, case_id: str, owner_id: str
    ) -> bool: ...


class InMemoryQuestionCampaignLedger:
    """Reference append-only campaign ledger with replay conflict detection."""

    def __init__(self) -> None:
        self._campaigns: dict[str, QuestionCampaignIdentity] = {}
        self._attempts: dict[tuple[str, str, int], QuestionCaseAttemptRecord] = {}
        self._completions: dict[str, QuestionCampaignCompletionRecord] = {}
        self._claims: dict[tuple[str, str], tuple[str, datetime]] = {}

    async def create_campaign(self, identity: QuestionCampaignIdentity) -> bool:
        existing = self._campaigns.get(identity.campaign_id)
        if existing is not None:
            if existing != identity:
                raise ValueError("question campaign id already belongs to different content")
            return False
        self._campaigns[identity.campaign_id] = identity
        return True

    async def append_attempt(self, record: QuestionCaseAttemptRecord) -> bool:
        if record.campaign_id not in self._campaigns:
            raise LookupError("question campaign is unavailable")
        key = (record.campaign_id, record.case_id, record.attempt_number)
        existing = self._attempts.get(key)
        if existing is not None:
            if existing != record:
                raise ValueError("question attempt id already belongs to different content")
            return False
        self._attempts[key] = record
        return True

    async def get_campaign(self, campaign_id: str) -> QuestionCampaignIdentity | None:
        return self._campaigns.get(campaign_id)

    async def list_attempts(self, campaign_id: str) -> tuple[QuestionCaseAttemptRecord, ...]:
        return tuple(
            sorted(
                (item for key, item in self._attempts.items() if key[0] == campaign_id),
                key=lambda item: (item.case_id, item.attempt_number),
            )
        )

    async def finalize_campaign(self, record: QuestionCampaignCompletionRecord) -> bool:
        if record.campaign_id not in self._campaigns:
            raise LookupError("question campaign is unavailable")
        existing = self._completions.get(record.campaign_id)
        if existing is not None:
            if existing != record:
                raise ValueError("question campaign completion conflicts with terminal content")
            return False
        self._completions[record.campaign_id] = record
        return True

    async def get_completion(self, campaign_id: str) -> QuestionCampaignCompletionRecord | None:
        return self._completions.get(campaign_id)

    async def claim_case(
        self,
        *,
        campaign_id: str,
        case_id: str,
        owner_id: str,
        claimed_at: datetime,
        lease_seconds: int,
    ) -> bool:
        if campaign_id not in self._campaigns:
            raise LookupError("question campaign is unavailable")
        if not owner_id or claimed_at.tzinfo is None or lease_seconds < 1:
            raise ValueError("question campaign case claim is invalid")
        key = (campaign_id, case_id)
        existing = self._claims.get(key)
        if existing is not None and existing[1] > claimed_at and existing[0] != owner_id:
            return False
        self._claims[key] = (owner_id, claimed_at + timedelta(seconds=lease_seconds))
        return True

    async def release_case_claim(self, *, campaign_id: str, case_id: str, owner_id: str) -> bool:
        key = (campaign_id, case_id)
        existing = self._claims.get(key)
        if existing is None or existing[0] != owner_id:
            return False
        del self._claims[key]
        return True


@dataclass(frozen=True, slots=True)
class CampaignTurnEvidence:
    """Typed terminal semantic projection used to reuse conversation assurance."""

    turn_id: str
    conversation_id: str
    principal_scope_digest: str
    question: str
    answer: str
    question_digest: str
    answer_digest: str
    evidence_manifest_digest: str
    evidence_refs: tuple[str, ...]
    verification_status: str
    verification_authority: str
    verification_reason_code: str
    verification_route_id: str | None
    checks_completed: int
    checks_total: int
    evidence_complete: bool
    ontology_release_digest: str
    graph_revision: str | None
    locale: str
    answer_model_identity: str | None


def campaign_turn_assessment_input(evidence: CampaignTurnEvidence) -> TurnAssessmentInput:
    """Map one terminal semantic result into the existing assurance contract."""

    return TurnAssessmentInput(
        turn_id=evidence.turn_id,
        conversation_id=evidence.conversation_id,
        principal_scope=evidence.principal_scope_digest,
        question=evidence.question,
        answer=evidence.answer,
        question_digest=evidence.question_digest,
        answer_digest=evidence.answer_digest,
        evidence_manifest_digest=evidence.evidence_manifest_digest,
        evidence_refs=evidence.evidence_refs,
        verification_status=evidence.verification_status,
        verification_authority=evidence.verification_authority,
        checks_completed=evidence.checks_completed,
        checks_total=evidence.checks_total,
        verification_reason_code=evidence.verification_reason_code,
        verification_route_id=evidence.verification_route_id,
        evidence_complete=evidence.evidence_complete,
        ontology_release=evidence.ontology_release_digest,
        graph_revision=evidence.graph_revision,
        locale=evidence.locale,
        answer_model_identity=evidence.answer_model_identity,
    )


def campaign_epistemic_record(
    *,
    case_id: str,
    question_universe_digest: str,
    status: EpistemicStatus,
    understanding_receipt_digest: str | None,
    completeness_receipt_digest: str | None,
    claim_proof_receipt_digests: Sequence[str] = (),
    closed_population_receipt_digest: str | None = None,
    hard_zero: QuestionCampaignHardZeroCounters | None = None,
) -> EpistemicQuestionRecord:
    """Build the existing epistemic record from campaign proof without widening authority."""

    effective_hard_zero = hard_zero or QuestionCampaignHardZeroCounters()
    disposition = {
        EpistemicStatus.VERIFIED_ANSWER: "answered",
        EpistemicStatus.VERIFIED_EMPTY: "answered",
        EpistemicStatus.QUALIFIED_ANSWER: "answered",
        EpistemicStatus.UNKNOWN_INCOMPLETE: "held",
        EpistemicStatus.UNKNOWN_STALE: "held",
        EpistemicStatus.UNKNOWN_CONFLICT: "held",
        EpistemicStatus.UNKNOWN_UNAVAILABLE: "held",
        EpistemicStatus.UNKNOWN_TEMPORAL_MISALIGNMENT: "held",
        EpistemicStatus.CLARIFICATION_REQUIRED: "clarification",
        EpistemicStatus.NOT_APPLICABLE: "unsupported",
        EpistemicStatus.UNSUPPORTED_CAPABILITY: "unsupported",
        EpistemicStatus.NOT_AUTHORIZED: "held",
        EpistemicStatus.ACTION_DRAFT_READY: "action_draft",
        EpistemicStatus.CANCELLED: "cancelled",
    }[status]
    cancelled = status is EpistemicStatus.CANCELLED
    return EpistemicQuestionRecord(
        question_id=case_id,
        transport_disposition=disposition,
        epistemic_status=status,
        question_universe_digest=question_universe_digest,
        understanding_receipt_digest=understanding_receipt_digest,
        completeness_receipt_digest=completeness_receipt_digest,
        claim_proof_receipt_digests=tuple(sorted(set(claim_proof_receipt_digests))),
        closed_population_receipt_digest=closed_population_receipt_digest,
        source_span_coverage=0.0 if cancelled else 1.0,
        semantic_atom_coverage=0.0 if cancelled else 1.0,
        ungrounded_claim_count=effective_hard_zero.unsupported_claim_count,
        hidden_scope_leak_count=effective_hard_zero.hidden_scope_leak_count,
        unsafe_mutation_survivor_count=effective_hard_zero.unsafe_mutation_survivor_count,
        locale_divergence_count=effective_hard_zero.locale_divergence_count,
    )


def _sum_hard_zero(
    attempts: Sequence[QuestionCaseAttemptRecord],
) -> QuestionCampaignHardZeroCounters:
    names = tuple(asdict(QuestionCampaignHardZeroCounters()))
    totals = {name: sum(getattr(item.hard_zero, name) for item in attempts) for name in names}
    return QuestionCampaignHardZeroCounters(**totals)


def _require_digest(name: str, value: str) -> None:
    if _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a canonical SHA-256 value")


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "CampaignTurnEvidence",
    "InMemoryQuestionCampaignLedger",
    "QuestionCampaignEvaluationReceipt",
    "QuestionCampaignHardZeroCounters",
    "QuestionCampaignIdentity",
    "QuestionCampaignLedger",
    "QuestionCampaignState",
    "QuestionCampaignTrigger",
    "QuestionCaseAttemptRecord",
    "build_question_campaign_identity",
    "campaign_epistemic_record",
    "campaign_turn_assessment_input",
    "evaluate_question_campaign",
]
