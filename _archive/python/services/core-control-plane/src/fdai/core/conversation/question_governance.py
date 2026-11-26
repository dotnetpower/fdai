"""Human review promotion and bounded question-campaign convergence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from fdai.core.conversation.question_adequacy import QuestionAdequacyReceipt
from fdai.core.conversation.question_golden import (
    GoldenQuestionCase,
    GoldenQuestionCorpus,
    build_golden_corpus,
)
from fdai.core.conversation.question_review_artifact import RepositorySafeQuestionReview
from fdai.core.conversation_assurance.models import AssuranceVerdict

_CAMPAIGN_ID_PATTERN = re.compile(r"qs:[0-9a-f]{64}")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_IDENTIFIER_PATTERN = re.compile(r"[a-z0-9][a-z0-9._:-]{0,255}")
_SEMVER_PATTERN = re.compile(r"([1-9][0-9]*)\.([0-9]+)\.([0-9]+)")


class QuestionFailureDecisionKind(StrEnum):
    """Terminal human decisions for one generated failure."""

    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class QuestionFailureReviewItem:
    """Digest-only generated failure awaiting explicit human review."""

    review_id: str
    campaign_id: str
    case_id: str
    semantic_pair_id: str
    ontology_release_digest: str
    question_digest: str
    answer_digest: str
    adequacy_receipt_digest: str
    submitted_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("review", self.review_id),
            ("case", self.case_id),
            ("semantic pair", self.semantic_pair_id),
        ):
            if _IDENTIFIER_PATTERN.fullmatch(value) is None:
                raise ValueError(f"question failure {name} id is invalid")
        if _CAMPAIGN_ID_PATTERN.fullmatch(self.campaign_id) is None:
            raise ValueError("question failure campaign id is invalid")
        for name, value in (
            ("release", self.ontology_release_digest),
            ("question", self.question_digest),
            ("answer", self.answer_digest),
            ("adequacy", self.adequacy_receipt_digest),
        ):
            _require_digest(f"question failure {name}", value)
        if self.submitted_at.tzinfo is None:
            raise ValueError("question failure submission time MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class QuestionFailureReviewDecision:
    """Append-only explicit human decision with a required promotion version."""

    review_id: str
    decision: QuestionFailureDecisionKind
    human_principal_digest: str
    human_authorization_receipt_digest: str
    authorization_expires_at: datetime
    reason_code: str
    decided_at: datetime
    target_corpus_version: str | None = None

    def __post_init__(self) -> None:
        if _IDENTIFIER_PATTERN.fullmatch(self.review_id) is None:
            raise ValueError("question failure decision review id is invalid")
        _require_digest("question failure human principal", self.human_principal_digest)
        _require_digest(
            "question failure human authorization",
            self.human_authorization_receipt_digest,
        )
        if self.decided_at.tzinfo is None:
            raise ValueError("question failure decision time MUST be timezone-aware")
        if self.authorization_expires_at.tzinfo is None:
            raise ValueError("question failure authorization expiry MUST be timezone-aware")
        if self.authorization_expires_at <= self.decided_at:
            raise ValueError("question failure human authorization MUST be current")
        if _IDENTIFIER_PATTERN.fullmatch(self.reason_code) is None:
            raise ValueError("question failure decision reason code is invalid")
        if self.decision is QuestionFailureDecisionKind.APPROVED:
            if (
                self.target_corpus_version is None
                or _SEMVER_PATTERN.fullmatch(self.target_corpus_version) is None
            ):
                raise ValueError("approved question failure requires a target corpus version")
        elif self.target_corpus_version is not None:
            raise ValueError("rejected question failure MUST NOT name a corpus version")


@dataclass(frozen=True, slots=True)
class GoldenQuestionPromotionReceipt:
    """No-authority proof that one approved failure changed corpus identity."""

    review_id: str
    source_release_digest: str
    prior_corpus_digest: str
    prior_corpus_version: str
    promoted_corpus_digest: str
    target_corpus_version: str
    human_principal_digest: str
    human_authorization_receipt_digest: str
    promoted_at: datetime
    receipt_digest: str
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if _IDENTIFIER_PATTERN.fullmatch(self.review_id) is None:
            raise ValueError("golden question promotion review id is invalid")
        for name, value in (
            ("source release", self.source_release_digest),
            ("prior corpus", self.prior_corpus_digest),
            ("promoted corpus", self.promoted_corpus_digest),
            ("human principal", self.human_principal_digest),
            ("human authorization", self.human_authorization_receipt_digest),
        ):
            _require_digest(f"golden question promotion {name}", value)
        if self.promoted_at.tzinfo is None:
            raise ValueError("golden question promotion time MUST be timezone-aware")
        if self.execution_authority:
            raise ValueError("golden question promotion MUST NOT carry execution authority")
        if self.receipt_digest != _digest(_promotion_receipt_body(self)):
            raise ValueError("golden question promotion receipt digest does not match content")


class QuestionFailureReviewLedger(Protocol):
    """Append-only generated failure review queue."""

    async def append_review_item(self, item: QuestionFailureReviewItem) -> bool: ...

    async def append_review_decision(self, decision: QuestionFailureReviewDecision) -> bool: ...

    async def get_review_item(self, review_id: str) -> QuestionFailureReviewItem | None: ...

    async def get_review_decision(self, review_id: str) -> QuestionFailureReviewDecision | None: ...


class InMemoryQuestionFailureReviewLedger:
    """Reference queue with one immutable decision per generated failure."""

    def __init__(self) -> None:
        self._items: dict[str, QuestionFailureReviewItem] = {}
        self._decisions: dict[str, QuestionFailureReviewDecision] = {}

    async def append_review_item(self, item: QuestionFailureReviewItem) -> bool:
        existing = self._items.get(item.review_id)
        if existing is not None:
            if existing != item:
                raise ValueError("question failure review id belongs to different content")
            return False
        self._items[item.review_id] = item
        return True

    async def append_review_decision(self, decision: QuestionFailureReviewDecision) -> bool:
        if decision.review_id not in self._items:
            raise LookupError("question failure review item is unavailable")
        existing = self._decisions.get(decision.review_id)
        if existing is not None:
            if existing != decision:
                raise ValueError("question failure decision is immutable")
            return False
        self._decisions[decision.review_id] = decision
        return True

    async def get_review_item(self, review_id: str) -> QuestionFailureReviewItem | None:
        return self._items.get(review_id)

    async def get_review_decision(self, review_id: str) -> QuestionFailureReviewDecision | None:
        return self._decisions.get(review_id)


async def append_generated_failure_for_review(
    *,
    ledger: QuestionFailureReviewLedger,
    projection: RepositorySafeQuestionReview,
    adequacy: QuestionAdequacyReceipt,
    ontology_release_digest: str,
    semantic_pair_id: str,
) -> bool:
    """Append one digest-only generated failure to the human review queue."""

    _require_digest("question failure source release", ontology_release_digest)
    if _IDENTIFIER_PATTERN.fullmatch(semantic_pair_id) is None:
        raise ValueError("question failure semantic pair id is invalid")
    if adequacy.verdict is AssuranceVerdict.PASS:
        raise ValueError("passed generated answers MUST NOT enter failure review")
    if projection.adequacy_verdict is not adequacy.verdict:
        raise ValueError("review projection verdict does not match adequacy")
    if (
        projection.case_id != adequacy.case_id
        or projection.adequacy_receipt_digest != adequacy.receipt_digest
    ):
        raise ValueError("review projection does not bind the generated adequacy receipt")
    return await ledger.append_review_item(
        QuestionFailureReviewItem(
            review_id=projection.record_id,
            campaign_id=projection.campaign_id,
            case_id=projection.case_id,
            semantic_pair_id=semantic_pair_id,
            ontology_release_digest=ontology_release_digest,
            question_digest=projection.question_digest,
            answer_digest=projection.answer_digest,
            adequacy_receipt_digest=projection.adequacy_receipt_digest,
            submitted_at=projection.recorded_at,
        )
    )


def promote_reviewed_failure(
    *,
    corpus: GoldenQuestionCorpus,
    item: QuestionFailureReviewItem,
    decision: QuestionFailureReviewDecision,
    promoted_cases: Sequence[GoldenQuestionCase],
    promoted_at: datetime,
) -> tuple[GoldenQuestionCorpus, GoldenQuestionPromotionReceipt]:
    """Append an approved bilingual pair only with a corpus version change."""

    if (
        decision.review_id != item.review_id
        or decision.decision is not QuestionFailureDecisionKind.APPROVED
    ):
        raise ValueError("golden promotion requires explicit approval for the review item")
    if promoted_at.tzinfo is None:
        raise ValueError("golden promotion time MUST be timezone-aware")
    if not decision.decided_at <= promoted_at < decision.authorization_expires_at:
        raise ValueError("golden promotion human authorization is not current")
    if decision.target_corpus_version is None or _version_tuple(
        decision.target_corpus_version
    ) <= _version_tuple(corpus.corpus_version):
        raise ValueError("golden promotion requires an increasing corpus version")
    if not promoted_cases or any(
        case.semantic_pair_id != item.semantic_pair_id for case in promoted_cases
    ):
        raise ValueError("golden promotion cases must bind the reviewed semantic pair")
    if item.semantic_pair_id in {case.semantic_pair_id for case in corpus.cases}:
        raise ValueError("golden promotion semantic pair already exists")
    promoted = build_golden_corpus(
        corpus_version=decision.target_corpus_version,
        cases=corpus.cases + tuple(promoted_cases),
    )
    provisional = GoldenQuestionPromotionReceipt.__new__(GoldenQuestionPromotionReceipt)
    for name, value in {
        "review_id": item.review_id,
        "source_release_digest": item.ontology_release_digest,
        "prior_corpus_digest": corpus.corpus_digest,
        "prior_corpus_version": corpus.corpus_version,
        "promoted_corpus_digest": promoted.corpus_digest,
        "target_corpus_version": promoted.corpus_version,
        "human_principal_digest": decision.human_principal_digest,
        "human_authorization_receipt_digest": decision.human_authorization_receipt_digest,
        "promoted_at": promoted_at,
        "execution_authority": False,
    }.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(
        provisional,
        "receipt_digest",
        _digest(_promotion_receipt_body(provisional)),
    )
    return promoted, GoldenQuestionPromotionReceipt(
        **{
            name: getattr(provisional, name)
            for name in GoldenQuestionPromotionReceipt.__dataclass_fields__
        }
    )


def _promotion_receipt_body(
    receipt: GoldenQuestionPromotionReceipt,
) -> dict[str, object]:
    return {
        "review_id": receipt.review_id,
        "source_release_digest": receipt.source_release_digest,
        "prior_corpus_digest": receipt.prior_corpus_digest,
        "prior_corpus_version": receipt.prior_corpus_version,
        "promoted_corpus_digest": receipt.promoted_corpus_digest,
        "target_corpus_version": receipt.target_corpus_version,
        "human_principal_digest": receipt.human_principal_digest,
        "human_authorization_receipt_digest": receipt.human_authorization_receipt_digest,
        "promoted_at": receipt.promoted_at.isoformat(),
        "execution_authority": receipt.execution_authority,
    }


@dataclass(frozen=True, slots=True)
class ManualQuestionCampaignReview:
    """One human-reviewed shadow campaign point on the empirical novelty curve."""

    campaign_id: str
    ontology_release_digest: str
    novelty_rate: float
    new_failure_count: int
    coverage_delta_count: int
    human_principal_digest: str
    human_review_receipt_digest: str
    reviewed_at: datetime
    mode: str = "shadow"

    def __post_init__(self) -> None:
        if _CAMPAIGN_ID_PATTERN.fullmatch(self.campaign_id) is None:
            raise ValueError("manual campaign review id is invalid")
        _require_digest("manual campaign release", self.ontology_release_digest)
        _require_digest("manual campaign human principal", self.human_principal_digest)
        _require_digest("manual campaign review receipt", self.human_review_receipt_digest)
        if not 0.0 <= self.novelty_rate <= 1.0:
            raise ValueError("manual campaign novelty rate MUST be in [0, 1]")
        if any(
            isinstance(value, bool) or not 0 <= value <= 100
            for value in (self.new_failure_count, self.coverage_delta_count)
        ):
            raise ValueError("manual campaign delta counters MUST be in [0, 100]")
        if self.reviewed_at.tzinfo is None:
            raise ValueError("manual campaign review time MUST be timezone-aware")
        if self.mode != "shadow":
            raise ValueError("manual question campaign reviews MUST remain shadow")


@dataclass(frozen=True, slots=True)
class QuestionConvergenceProfile:
    """Human-approved policy for stopping repeated low-novelty scheduling."""

    profile_digest: str
    human_approver_digest: str
    approval_receipt_digest: str
    low_novelty_threshold: float
    required_consecutive_runs: int
    minimum_manual_campaigns: int = 3

    def __post_init__(self) -> None:
        _require_digest("question convergence profile", self.profile_digest)
        _require_digest("question convergence approver", self.human_approver_digest)
        _require_digest("question convergence approval", self.approval_receipt_digest)
        if not 0.0 <= self.low_novelty_threshold < 1.0:
            raise ValueError("question convergence threshold MUST be in [0, 1)")
        if not 2 <= self.required_consecutive_runs <= 10:
            raise ValueError("question convergence consecutive runs MUST be in [2, 10]")
        if not 3 <= self.minimum_manual_campaigns <= 10:
            raise ValueError("question convergence manual campaigns MUST be in [3, 10]")


@dataclass(frozen=True, slots=True)
class QuestionConvergenceReceipt:
    """Scheduling decision and empirical novelty curve for one release."""

    ontology_release_digest: str
    profile_digest: str
    approval_receipt_digest: str
    manual_campaign_count: int
    consecutive_low_novelty_runs: int
    novelty_curve: tuple[float, ...]
    campaign_review_digests: tuple[str, ...]
    stop_scheduling: bool
    reopened: bool
    reason: str
    receipt_digest: str

    def __post_init__(self) -> None:
        _require_digest("question convergence release", self.ontology_release_digest)
        _require_digest("question convergence profile", self.profile_digest)
        _require_digest("question convergence approval", self.approval_receipt_digest)
        if self.manual_campaign_count != len(self.novelty_curve):
            raise ValueError("question convergence campaign count is inconsistent")
        if not 0 <= self.consecutive_low_novelty_runs <= self.manual_campaign_count:
            raise ValueError("question convergence novelty streak is inconsistent")
        if len(self.campaign_review_digests) != self.manual_campaign_count:
            raise ValueError("question convergence review count is inconsistent")
        for digest in self.campaign_review_digests:
            _require_digest("question convergence campaign review", digest)
        if self.receipt_digest != _digest(_convergence_receipt_body(self)):
            raise ValueError("question convergence receipt digest does not match content")


def evaluate_question_convergence(
    *,
    target_release_digest: str,
    profile: QuestionConvergenceProfile,
    campaigns: Sequence[ManualQuestionCampaignReview],
    evaluated_at: datetime,
) -> QuestionConvergenceReceipt:
    """Stop only after reviewed low novelty; reopen on release, failure, or coverage change."""

    _require_digest("question convergence target release", target_release_digest)
    if evaluated_at.tzinfo is None:
        raise ValueError("question convergence evaluation time MUST be timezone-aware")
    if any(item.reviewed_at > evaluated_at for item in campaigns):
        raise ValueError("manual campaign review time MUST NOT be in the future")
    ordered = tuple(sorted(campaigns, key=lambda item: (item.reviewed_at, item.campaign_id)))
    if len({item.campaign_id for item in ordered}) != len(ordered):
        raise ValueError("manual campaign reviews MUST have unique campaign ids")
    current = tuple(
        item for item in ordered if item.ontology_release_digest == target_release_digest
    )
    release_changed = bool(ordered) and ordered[-1].ontology_release_digest != target_release_digest
    streak = 0
    for item in reversed(current):
        if (
            item.new_failure_count
            or item.coverage_delta_count
            or item.novelty_rate > profile.low_novelty_threshold
        ):
            break
        streak += 1
    reopened = release_changed or bool(
        current and (current[-1].new_failure_count or current[-1].coverage_delta_count)
    )
    enough_manual = len(current) >= profile.minimum_manual_campaigns
    stop = enough_manual and streak >= profile.required_consecutive_runs and not reopened
    if release_changed:
        reason = "release_change_reopened_exploration"
    elif current and current[-1].new_failure_count:
        reason = "new_failure_reopened_exploration"
    elif current and current[-1].coverage_delta_count:
        reason = "coverage_delta_reopened_exploration"
    elif not enough_manual:
        reason = "manual_campaign_floor_not_met"
    elif streak < profile.required_consecutive_runs:
        reason = "low_novelty_streak_not_met"
    else:
        reason = "approved_convergence_reached"
    novelty_curve = tuple(item.novelty_rate for item in current)
    campaign_review_digests = tuple(_manual_review_digest(item) for item in current)
    provisional = QuestionConvergenceReceipt.__new__(QuestionConvergenceReceipt)
    for name, value in {
        "ontology_release_digest": target_release_digest,
        "profile_digest": profile.profile_digest,
        "approval_receipt_digest": profile.approval_receipt_digest,
        "manual_campaign_count": len(current),
        "consecutive_low_novelty_runs": streak,
        "novelty_curve": novelty_curve,
        "campaign_review_digests": campaign_review_digests,
        "stop_scheduling": stop,
        "reopened": reopened,
        "reason": reason,
    }.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(
        provisional,
        "receipt_digest",
        _digest(_convergence_receipt_body(provisional)),
    )
    return QuestionConvergenceReceipt(
        ontology_release_digest=target_release_digest,
        profile_digest=profile.profile_digest,
        approval_receipt_digest=profile.approval_receipt_digest,
        manual_campaign_count=len(current),
        consecutive_low_novelty_runs=streak,
        novelty_curve=novelty_curve,
        campaign_review_digests=campaign_review_digests,
        stop_scheduling=stop,
        reopened=reopened,
        reason=reason,
        receipt_digest=provisional.receipt_digest,
    )


def _convergence_receipt_body(
    receipt: QuestionConvergenceReceipt,
) -> dict[str, object]:
    return {
        "ontology_release_digest": receipt.ontology_release_digest,
        "manual_campaign_count": receipt.manual_campaign_count,
        "consecutive_low_novelty_runs": receipt.consecutive_low_novelty_runs,
        "novelty_curve": receipt.novelty_curve,
        "campaign_review_digests": receipt.campaign_review_digests,
        "stop_scheduling": receipt.stop_scheduling,
        "reopened": receipt.reopened,
        "reason": receipt.reason,
        "profile_digest": receipt.profile_digest,
        "approval_receipt_digest": receipt.approval_receipt_digest,
    }


def _manual_review_digest(record: ManualQuestionCampaignReview) -> str:
    body = asdict(record)
    body["reviewed_at"] = record.reviewed_at.isoformat()
    return _digest(body)


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _SEMVER_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("golden corpus version is invalid")
    return tuple(int(item) for item in match.groups())  # type: ignore[return-value]


def _require_digest(name: str, value: str) -> None:
    if _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a canonical SHA-256 value")


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "GoldenQuestionPromotionReceipt",
    "InMemoryQuestionFailureReviewLedger",
    "ManualQuestionCampaignReview",
    "QuestionConvergenceProfile",
    "QuestionConvergenceReceipt",
    "QuestionFailureDecisionKind",
    "QuestionFailureReviewDecision",
    "QuestionFailureReviewItem",
    "QuestionFailureReviewLedger",
    "append_generated_failure_for_review",
    "evaluate_question_convergence",
    "promote_reviewed_failure",
]
