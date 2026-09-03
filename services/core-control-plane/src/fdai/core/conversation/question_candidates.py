"""Validate natural-language candidates against deterministic question cases."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Protocol

from fdai.core.conversation.question_universe import GeneratedQuestionCase

_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_URL_PATTERN = re.compile(r"(?:https?://|[A-Za-z0-9-]+\.(?:azure|windows)\.net\b)", re.I)
_RESOURCE_ID_PATTERN = re.compile(
    r"/(?:subscriptions|resourceGroups|providers)/"
    r"|\bBearer(?:\s+|:)\S+"
    r"|\beyJ[A-Za-z0-9_-]+\."
    r"|(?:^|[?&\s])sig=[^&\s]+"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}\b",
    re.I,
)
_CREDENTIAL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])"
    r"(?:password|pwd|accountkey|sharedaccesskey|clientsecret|api[-_]?key|secretaccesskey"
    r"|access[-_]?token|refresh[-_]?token|secret|token)"
    r"\s*[:=]\s*[^;,\s]+"
    r"|\b[A-Za-z][A-Za-z0-9+.-]*://[^/\s:@]+:[^@\s]+@",
    re.I,
)
_EXECUTABLE_QUERY_PATTERN = re.compile(
    r"(?:^|\s)(?:SELECT\s+.+\s+FROM|az\s+|kubectl\s+|curl\s+|pwsh\s+|powershell\s+)",
    re.I,
)
_PROMPT_INJECTION_PATTERN = re.compile(
    r"ignore\s+(?:all\s+)?previous"
    r"|disregard\s+(?:all\s+)?(?:prior|previous)"
    r"|(?:override|replace)\s+(?:the\s+)?system"
    r"|(?:bypass|suspend)\s+(?:all\s+)?(?:safety\s+)?(?:rules|restrictions)"
    r"|system\s+prompt|developer\s+message|이전\s+지시.*무시",
    re.I,
)
_HANGUL_PATTERN = re.compile(r"[가-힣]")
_MAX_QUESTION_LENGTH = 400
_MIN_QUESTION_LENGTH = 8
_MAX_PRIOR_QUESTIONS = 10_000
_TOKEN_SIMILARITY_LIMIT = 0.85
_EMBEDDING_SIMILARITY_LIMIT = 0.92
_EQUIVALENCE_CONFIDENCE = 0.85


@dataclass(frozen=True, slots=True)
class NaturalLanguageQuestionCandidate:
    """One model-proposed wording bound to immutable server-owned case fields."""

    schema_version: str
    case_id: str
    perspective: str
    locale: str
    question: str
    required_capabilities: tuple[str, ...]
    allowed_dispositions: tuple[str, ...]
    anchor_kind: str
    action_posture: str
    rule_state: str


@dataclass(frozen=True, slots=True)
class QuestionModelUsage:
    """Bounded model metering attached to one generation or review call."""

    model_calls: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_microusd: int = 0

    def __post_init__(self) -> None:
        if any(
            value < 0
            for value in (
                self.model_calls,
                self.prompt_tokens,
                self.completion_tokens,
                self.cost_microusd,
            )
        ):
            raise ValueError("question model usage MUST be non-negative")

    def __add__(self, other: QuestionModelUsage) -> QuestionModelUsage:
        return QuestionModelUsage(
            model_calls=self.model_calls + other.model_calls,
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cost_microusd=self.cost_microusd + other.cost_microusd,
        )


@dataclass(frozen=True, slots=True)
class QuestionCandidateGeneration:
    """One untrusted candidate payload plus provider-reported usage."""

    payload: Mapping[str, object]
    usage: QuestionModelUsage


@dataclass(frozen=True, slots=True)
class QuestionCandidateReview:
    """Independent semantic and embedding review over one candidate."""

    reviewer_identity: str
    reviewer_family: str
    equivalent: bool
    same_locale: bool
    same_result_shape: bool
    same_scope: bool
    same_evidence_authority: bool
    confidence: float
    max_embedding_similarity: float
    usage: QuestionModelUsage = QuestionModelUsage(model_calls=1)
    embedding_space_digest: str | None = None
    embedding_model_version: str | None = None
    embedding_dimension: int | None = None
    candidate_embedding_digest: str | None = None
    nearest_question_fingerprint: str | None = None

    def __post_init__(self) -> None:
        embedding_values = (
            self.embedding_space_digest,
            self.embedding_model_version,
            self.embedding_dimension,
            self.candidate_embedding_digest,
        )
        if any(value is not None for value in embedding_values) and not all(
            value is not None for value in embedding_values
        ):
            raise ValueError("question candidate embedding identity MUST be complete")
        if self.embedding_space_digest is not None:
            _require_digest("question candidate embedding space", self.embedding_space_digest)
            _require_digest(
                "question candidate embedding vector", str(self.candidate_embedding_digest)
            )
            if not self.embedding_model_version or len(self.embedding_model_version) > 128:
                raise ValueError("question candidate embedding model version MUST be bounded")
            if (
                isinstance(self.embedding_dimension, bool)
                or not isinstance(self.embedding_dimension, int)
                or not 1 <= self.embedding_dimension <= 65_536
            ):
                raise ValueError("question candidate embedding dimension MUST be in [1, 65536]")
        if self.nearest_question_fingerprint is not None:
            _require_digest(
                "question candidate nearest fingerprint", self.nearest_question_fingerprint
            )


class QuestionCandidateReviewer(Protocol):
    """Review semantic equivalence without gaining query or action authority."""

    @property
    def max_usage_per_call(self) -> QuestionModelUsage | None: ...

    async def review(
        self,
        *,
        candidate: NaturalLanguageQuestionCandidate,
        expected_case: GeneratedQuestionCase,
        prior_questions: tuple[str, ...],
    ) -> QuestionCandidateReview: ...


@dataclass(frozen=True, slots=True)
class QuestionCandidateValidationReceipt:
    """Stable terminal validation state for one generated candidate attempt."""

    case_id: str
    accepted: bool
    reason: str
    candidate_digest: str
    fingerprint: str | None
    review_digest: str | None
    generation_profile_digest: str


@dataclass(frozen=True, slots=True)
class ValidatedQuestion:
    """Environment-generic wording bound to one exact deterministic case."""

    candidate: NaturalLanguageQuestionCandidate
    candidate_digest: str
    fingerprint: str
    validation_receipt_digest: str
    review: QuestionCandidateReview


@dataclass(frozen=True, slots=True)
class QuestionCandidateValidationResult:
    """Accepted question or a stable typed hold without raw provider output."""

    question: ValidatedQuestion | None
    receipt: QuestionCandidateValidationReceipt


async def validate_question_candidate(
    *,
    payload: Mapping[str, object],
    expected_case: GeneratedQuestionCase,
    generation_profile_digest: str,
    generator_family: str,
    prior_questions: Sequence[str],
    pantheon_names: Sequence[str],
    reviewer: QuestionCandidateReviewer,
) -> QuestionCandidateValidationResult:
    """Validate immutable fields, safety, uniqueness, and semantic equivalence.

    Invalid output becomes a stable hold reason. The function never repairs model
    text, executes generated content, or stores raw failed provider responses.
    """

    _require_digest("generation profile digest", generation_profile_digest)
    if not generator_family:
        raise ValueError("question generator family MUST be non-empty")
    if len(prior_questions) > _MAX_PRIOR_QUESTIONS:
        raise ValueError("prior question corpus exceeds its bound")
    if not pantheon_names:
        raise ValueError("question candidate policy requires pantheon names")
    provider_payload_digest = _digest(payload)
    candidate, parsed_reason = _parse_candidate(payload, expected_case)
    if candidate is None:
        return _held(
            expected_case,
            reason=parsed_reason,
            candidate_digest=provider_payload_digest,
            generation_profile_digest=generation_profile_digest,
        )
    candidate_digest = _digest(asdict(candidate))
    reason: str | None = _validate_text(
        candidate,
        expected_case,
        pantheon_names=pantheon_names,
    )
    fingerprint = question_fingerprint(candidate.question)
    if reason is None:
        reason = _duplicate_reason(candidate.question, fingerprint, prior_questions)
    if reason is not None:
        return _held(
            expected_case,
            reason=reason,
            candidate_digest=candidate_digest,
            fingerprint=fingerprint,
            generation_profile_digest=generation_profile_digest,
        )
    review = await reviewer.review(
        candidate=candidate,
        expected_case=expected_case,
        prior_questions=tuple(prior_questions),
    )
    review_digest = _digest(asdict(review))
    review_reason = _review_reason(review, generator_family=generator_family)
    if review_reason is not None:
        return _held(
            expected_case,
            reason=review_reason,
            candidate_digest=candidate_digest,
            fingerprint=fingerprint,
            review_digest=review_digest,
            generation_profile_digest=generation_profile_digest,
        )
    receipt = QuestionCandidateValidationReceipt(
        case_id=expected_case.case_id,
        accepted=True,
        reason="accepted",
        candidate_digest=candidate_digest,
        fingerprint=fingerprint,
        review_digest=review_digest,
        generation_profile_digest=generation_profile_digest,
    )
    receipt_digest = _digest(asdict(receipt))
    return QuestionCandidateValidationResult(
        question=ValidatedQuestion(
            candidate=candidate,
            candidate_digest=candidate_digest,
            fingerprint=fingerprint,
            validation_receipt_digest=receipt_digest,
            review=review,
        ),
        receipt=receipt,
    )


def question_fingerprint(question: str) -> str:
    """Return a locale-neutral exact duplicate identity for one wording."""

    normalized = unicodedata.normalize("NFC", " ".join(question.casefold().split()))
    return f"sha256:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"


def question_case_contract(case: GeneratedQuestionCase) -> dict[str, object]:
    """Project the complete server-owned semantics supplied to wording models."""

    return {
        "schema_version": "1.0.0",
        "case_id": case.case_id,
        "declaration_id": case.declaration_id,
        "locale": case.locale,
        "case_class": case.case_class.value,
        "perspective": case.perspective.value,
        "required_capability": case.required_capability.value,
        "evidence_posture": case.evidence_posture.value,
        "anchor_kind": case.anchor_kind.value,
        "expected_posture": case.expected_posture.value,
        "action_posture": case.action_posture,
        "rule_state": case.rule_state.value,
        "path_depth": case.path_depth,
        "result_bound": case.result_bound,
        "entity_state": case.entity_state.value,
        "temporal_state": case.temporal_state.value,
        "causal_result": case.causal_result.value,
        "presentation_shape": case.presentation_shape.value,
    }


def _parse_candidate(
    payload: Mapping[str, object],
    expected_case: GeneratedQuestionCase,
) -> tuple[NaturalLanguageQuestionCandidate | None, str]:
    if set(payload) != {"question"}:
        return None, "candidate_schema_invalid"
    if not isinstance(payload.get("question"), str):
        return None, "candidate_schema_invalid"
    candidate = NaturalLanguageQuestionCandidate(
        schema_version="1.0.0",
        case_id=expected_case.case_id,
        perspective=expected_case.perspective.value,
        locale=expected_case.locale,
        question=str(payload["question"]).strip(),
        required_capabilities=(expected_case.required_capability.value,),
        allowed_dispositions=(_disposition(expected_case),),
        anchor_kind=expected_case.anchor_kind.value,
        action_posture=expected_case.action_posture,
        rule_state=expected_case.rule_state.value,
    )
    return candidate, ""


def _validate_text(
    candidate: NaturalLanguageQuestionCandidate,
    expected_case: GeneratedQuestionCase,
    *,
    pantheon_names: Sequence[str],
) -> str | None:
    question = candidate.question
    if not _MIN_QUESTION_LENGTH <= len(question) <= _MAX_QUESTION_LENGTH:
        return "candidate_length_invalid"
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in question):
        return "candidate_control_character_rejected"
    has_hangul = _HANGUL_PATTERN.search(question) is not None
    if (candidate.locale.startswith("ko") and not has_hangul) or (
        candidate.locale.startswith("en") and has_hangul
    ):
        return "candidate_locale_mismatch"
    if (
        _UUID_PATTERN.search(question)
        or _URL_PATTERN.search(question)
        or _RESOURCE_ID_PATTERN.search(question)
        or _CREDENTIAL_PATTERN.search(question)
    ):
        return "candidate_environment_identifier_rejected"
    if _EXECUTABLE_QUERY_PATTERN.search(question):
        return "candidate_executable_query_rejected"
    if _PROMPT_INJECTION_PATTERN.search(question):
        return "candidate_prompt_injection_rejected"
    if expected_case.anchor_kind.value == "server_scope":
        normalized = question.casefold()
        if any(
            re.search(rf"\b{re.escape(name.casefold())}\b", normalized) for name in pantheon_names
        ):
            return "candidate_server_scope_agent_rejected"
    if expected_case.action_posture == "draft_only" and not _is_draft_wording(
        question, locale=candidate.locale
    ):
        return "candidate_action_posture_rejected"
    return None


def _duplicate_reason(
    question: str,
    fingerprint: str,
    prior_questions: Sequence[str],
) -> str | None:
    if any(question_fingerprint(item) == fingerprint for item in prior_questions):
        return "candidate_duplicate_rejected"
    tokens = _tokens(question)
    if any(_jaccard(tokens, _tokens(item)) >= _TOKEN_SIMILARITY_LIMIT for item in prior_questions):
        return "candidate_near_duplicate_rejected"
    return None


def _review_reason(review: QuestionCandidateReview, *, generator_family: str) -> str | None:
    if not review.reviewer_identity or not review.reviewer_family:
        return "candidate_review_invalid"
    if review.reviewer_family == generator_family:
        return "candidate_review_not_independent"
    if not 0.0 <= review.confidence <= 1.0 or not 0.0 <= review.max_embedding_similarity <= 1.0:
        return "candidate_review_invalid"
    if review.max_embedding_similarity >= _EMBEDDING_SIMILARITY_LIMIT:
        return "candidate_embedding_duplicate_rejected"
    if review.confidence < _EQUIVALENCE_CONFIDENCE:
        return "candidate_equivalence_low_confidence"
    if not all(
        (
            review.equivalent,
            review.same_locale,
            review.same_result_shape,
            review.same_scope,
            review.same_evidence_authority,
        )
    ):
        return "candidate_equivalence_rejected"
    return None


def _held(
    expected_case: GeneratedQuestionCase,
    *,
    reason: str,
    candidate_digest: str,
    generation_profile_digest: str,
    fingerprint: str | None = None,
    review_digest: str | None = None,
) -> QuestionCandidateValidationResult:
    return QuestionCandidateValidationResult(
        question=None,
        receipt=QuestionCandidateValidationReceipt(
            case_id=expected_case.case_id,
            accepted=False,
            reason=reason,
            candidate_digest=candidate_digest,
            fingerprint=fingerprint,
            review_digest=review_digest,
            generation_profile_digest=generation_profile_digest,
        ),
    )


def _disposition(case: GeneratedQuestionCase) -> str:
    return {
        "answer": "answered",
        "clarify": "clarification",
        "hold": "held",
        "unsupported": "unsupported",
        "action_draft": "action_draft",
    }[case.expected_posture.value]


def _is_draft_wording(question: str, *, locale: str) -> bool:
    normalized = question.casefold()
    if locale.startswith("ko"):
        return "초안" in normalized or "제안" in normalized
    return "draft" in normalized or "propose" in normalized or "proposal" in normalized


def _tokens(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFC", value.casefold())
    return frozenset(re.findall(r"[a-z0-9가-힣]+", normalized))


def _jaccard(first: frozenset[str], second: frozenset[str]) -> float:
    if not first and not second:
        return 1.0
    return len(first & second) / len(first | second)


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
    "NaturalLanguageQuestionCandidate",
    "QuestionCandidateReview",
    "QuestionCandidateReviewer",
    "QuestionCandidateValidationReceipt",
    "QuestionCandidateValidationResult",
    "ValidatedQuestion",
    "question_case_contract",
    "question_fingerprint",
    "validate_question_candidate",
]
