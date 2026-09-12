"""Strict local-only decoder for A3-E shadow-cohort corpus documents.

Pure and offline. The decoder turns one bounded JSON document into the
:mod:`~fdai.core.standing_authority.shadow_cohort_runner` inputs
(:class:`CohortManifest`, the :class:`CohortCaseInput` corpus, and the per-case
elapsed map). It opens no socket, reads no environment, and reaches no provider,
Azure endpoint, database, or promotion registry.

Fail-closed rules:

- The document MUST declare ``venue="local"`` and
  ``evidence_class="synthetic_development"``. Any other value is rejected, so a
  synthetic corpus can never be relabelled as runtime or governed evidence.
- The schema is closed: an unknown key anywhere is an error rather than an ignored
  field.
- Size, case count, review count, and per-case elapsed values are bounded, so a
  malformed document cannot drive an unbounded run.

The resulting receipt remains development evidence. It cannot satisfy the governed
runtime cohort, independent review, or human approval required by issue #632.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

from fdai.core.standing_authority.lifecycle import LifecycleFence
from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
    content_digest,
    instant,
)
from fdai.core.standing_authority.promotion_candidate_models import (
    CandidateReviewRecord,
    DenialReason,
    PromotionCandidateRecord,
    ReviewDecision,
)
from fdai.core.standing_authority.promotion_candidate_ops import build_candidate_record
from fdai.core.standing_authority.shadow_cohort_runner import (
    COHORT_TIMEOUT_PER_CASE_S,
    COHORT_TIMEOUT_TOTAL_S,
    CohortCaseInput,
    CohortDisposition,
    CohortExternalDenialInput,
    CohortManifest,
    CohortManifestEntry,
    build_manifest,
)

CORPUS_SCHEMA_VERSION: Final[str] = "a3e-local-cohort-v1"
LOCAL_VENUE: Final[str] = "local"
LOCAL_EVIDENCE_CLASS: Final[str] = "synthetic_development"

#: Hard input bounds. They cap the work one document can request before
#: ``run_cohort`` applies its own total, no-progress, and per-case timeouts.
MAX_CORPUS_BYTES: Final[int] = 1 << 20
MAX_CASES: Final[int] = 256
MAX_REVIEWS_PER_CASE: Final[int] = 16
MAX_ACTION_TYPES: Final[int] = 32
MAX_EVIDENCE_ITEMS: Final[int] = 32

_DOCUMENT_KEYS: Final[frozenset[str]] = frozenset(
    {"schema_version", "venue", "evidence_class", "source_revision_id", "cases"}
)
_CASE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "case_id",
        "expected_disposition",
        "expected_denial_reason",
        "elapsed_s",
        "candidate",
        "reviews",
        "external_denial",
    }
)
_CANDIDATE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "family_id",
        "revision_id",
        "fence",
        "eligible_action_types",
        "ineligible_provider_action_types",
        "evidence_requirements",
        "source_revision_id",
        "creator_principal",
        "authentication_evidence_digest",
        "created_at",
        "required_reviewer_principals",
        "quorum_required",
    }
)
_FENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"family_id", "revision_id", "fencing_generation", "transition_digest"}
)
_REVIEW_KEYS: Final[frozenset[str]] = frozenset(
    {
        "reviewer_principal",
        "decision",
        "reviewed_at",
        "authentication_evidence_digest",
        "evidence_digests",
    }
)
_DENIAL_KEYS: Final[frozenset[str]] = frozenset(
    {"reason", "detail", "actor_ref", "authentication_evidence_digest", "occurred_at"}
)


class CohortCorpusError(AuthorizationLifecycleError):
    """Raised when a corpus document is malformed, unbounded, or non-local."""


@dataclass(frozen=True, slots=True)
class DecodedCorpus:
    """Validated local-only inputs for one :func:`run_cohort` invocation."""

    manifest: CohortManifest
    corpus: tuple[CohortCaseInput, ...]
    per_case_elapsed_s: Mapping[str, float]
    venue: str = LOCAL_VENUE
    evidence_class: str = LOCAL_EVIDENCE_CLASS

    def __post_init__(self) -> None:
        if self.venue != LOCAL_VENUE or self.evidence_class != LOCAL_EVIDENCE_CLASS:
            raise CohortCorpusError("decoded corpus MUST remain local synthetic evidence")


def decode_corpus_document(raw: str) -> DecodedCorpus:
    """Decode one bounded local corpus document. Fail closed on anything unexpected."""

    if len(raw.encode("utf-8")) > MAX_CORPUS_BYTES:
        raise CohortCorpusError(f"corpus document exceeds {MAX_CORPUS_BYTES} bytes")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CohortCorpusError(f"corpus document is not valid JSON: {error.msg}") from error
    if not isinstance(document, dict):
        raise CohortCorpusError("corpus document MUST be a JSON object")
    _require_exact_keys("document", document, _DOCUMENT_KEYS)

    if _text(document, "schema_version") != CORPUS_SCHEMA_VERSION:
        raise CohortCorpusError(f"schema_version MUST be {CORPUS_SCHEMA_VERSION!r}")
    if _text(document, "venue") != LOCAL_VENUE:
        raise CohortCorpusError("corpus venue MUST be 'local'; runtime venues are not decodable")
    if _text(document, "evidence_class") != LOCAL_EVIDENCE_CLASS:
        raise CohortCorpusError(
            "corpus evidence_class MUST be 'synthetic_development'; "
            "governed evidence cannot be produced locally"
        )
    source_revision_id = _text(document, "source_revision_id")

    cases = document["cases"]
    if not isinstance(cases, list) or not cases:
        raise CohortCorpusError("corpus MUST declare a non-empty 'cases' list")
    if len(cases) > MAX_CASES:
        raise CohortCorpusError(f"corpus declares more than {MAX_CASES} cases")

    entries: list[CohortManifestEntry] = []
    corpus: list[CohortCaseInput] = []
    elapsed: dict[str, float] = {}
    total_elapsed = 0.0

    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise CohortCorpusError(f"case {index} MUST be a JSON object")
        _require_exact_keys(f"case {index}", case, _CASE_KEYS)
        case_id = _text(case, "case_id")
        if case_id in elapsed:
            raise CohortCorpusError(f"duplicate case_id in corpus document: {case_id}")
        disposition = _enum(CohortDisposition, _text(case, "expected_disposition"), "disposition")
        raw_reason = case["expected_denial_reason"]
        denial_reason = (
            None if raw_reason is None else _enum(DenialReason, str(raw_reason), "denial reason")
        )
        entries.append(
            CohortManifestEntry(
                case_id=case_id,
                expected_disposition=disposition,
                expected_denial_reason=denial_reason,
            )
        )
        case_elapsed = _elapsed(case["elapsed_s"], case_id)
        total_elapsed += case_elapsed
        if total_elapsed > COHORT_TIMEOUT_TOTAL_S:
            raise CohortCorpusError(
                f"declared elapsed time exceeds the {COHORT_TIMEOUT_TOTAL_S}s total bound"
            )
        elapsed[case_id] = case_elapsed
        record = _candidate(case["candidate"], case_id)
        corpus.append(
            CohortCaseInput(
                case_id=case_id,
                record=record,
                review_steps=_reviews(case["reviews"], record.candidate_id, case_id),
                external_denial=_external_denial(case["external_denial"], case_id),
            )
        )

    manifest = build_manifest(
        source_revision_id=source_revision_id,
        entries=tuple(entries),
    )
    return DecodedCorpus(
        manifest=manifest,
        corpus=tuple(corpus),
        per_case_elapsed_s=elapsed,
    )


def _require_exact_keys(label: str, value: Mapping[str, Any], allowed: frozenset[str]) -> None:
    keys = set(value)
    unknown = sorted(keys - allowed)
    if unknown:
        raise CohortCorpusError(f"{label} has unknown key(s): {unknown}")
    missing = sorted(allowed - keys)
    if missing:
        raise CohortCorpusError(f"{label} is missing required key(s): {missing}")


def _text(value: Mapping[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise CohortCorpusError(f"{key} MUST be non-empty text")
    return raw


def _enum[EnumT: StrEnum](enum_cls: type[EnumT], raw: str, label: str) -> EnumT:
    try:
        return enum_cls(raw)
    except ValueError as error:
        raise CohortCorpusError(f"unknown {label}: {raw!r}") from error


def _elapsed(raw: object, case_id: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise CohortCorpusError(f"case {case_id} elapsed_s MUST be a number")
    value = float(raw)
    if value < 0.0 or value != value or value in {float("inf"), float("-inf")}:
        raise CohortCorpusError(f"case {case_id} elapsed_s MUST be finite and non-negative")
    if value > COHORT_TIMEOUT_PER_CASE_S:
        raise CohortCorpusError(
            f"case {case_id} elapsed_s exceeds the {COHORT_TIMEOUT_PER_CASE_S}s per-case bound"
        )
    return value


def _strings(value: Mapping[str, Any], key: str, case_id: str, limit: int) -> tuple[str, ...]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise CohortCorpusError(f"case {case_id} {key} MUST be a list")
    if len(raw) > limit:
        raise CohortCorpusError(f"case {case_id} {key} exceeds {limit} entries")
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise CohortCorpusError(f"case {case_id} {key} MUST contain non-empty text")
    return tuple(str(item) for item in raw)


def _timestamp(value: Mapping[str, Any], key: str, case_id: str) -> datetime:
    raw = _text(value, key)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise CohortCorpusError(f"case {case_id} {key} MUST be an RFC 3339 instant") from error
    if parsed.tzinfo is None:
        raise CohortCorpusError(f"case {case_id} {key} MUST be timezone-aware")
    return parsed.astimezone(UTC)


def _fence(value: object, case_id: str) -> LifecycleFence:
    if not isinstance(value, dict):
        raise CohortCorpusError(f"case {case_id} fence MUST be a JSON object")
    _require_exact_keys(f"case {case_id} fence", value, _FENCE_KEYS)
    generation = value["fencing_generation"]
    if isinstance(generation, bool) or not isinstance(generation, int):
        raise CohortCorpusError(f"case {case_id} fencing_generation MUST be an integer")
    return LifecycleFence(
        family_id=_text(value, "family_id"),
        revision_id=_text(value, "revision_id"),
        fencing_generation=generation,
        transition_digest=_text(value, "transition_digest"),
    )


def _candidate(value: object, case_id: str) -> PromotionCandidateRecord:
    if not isinstance(value, dict):
        raise CohortCorpusError(f"case {case_id} candidate MUST be a JSON object")
    _require_exact_keys(f"case {case_id} candidate", value, _CANDIDATE_KEYS)
    quorum = value["quorum_required"]
    if isinstance(quorum, bool) or not isinstance(quorum, int):
        raise CohortCorpusError(f"case {case_id} quorum_required MUST be an integer")
    return build_candidate_record(
        family_id=_text(value, "family_id"),
        revision_id=_text(value, "revision_id"),
        fence=_fence(value["fence"], case_id),
        eligible_action_types=_strings(value, "eligible_action_types", case_id, MAX_ACTION_TYPES),
        ineligible_provider_action_types=_strings(
            value, "ineligible_provider_action_types", case_id, MAX_ACTION_TYPES
        ),
        evidence_requirements=_strings(value, "evidence_requirements", case_id, MAX_EVIDENCE_ITEMS),
        source_revision_id=_text(value, "source_revision_id"),
        creator_principal=_text(value, "creator_principal"),
        authentication_evidence_digest=_text(value, "authentication_evidence_digest"),
        created_at=_timestamp(value, "created_at", case_id),
        required_reviewer_principals=_strings(
            value, "required_reviewer_principals", case_id, MAX_ACTION_TYPES
        ),
        quorum_required=quorum,
    )


def _reviews(
    value: object,
    candidate_id: str,
    case_id: str,
) -> tuple[CandidateReviewRecord, ...]:
    if not isinstance(value, list):
        raise CohortCorpusError(f"case {case_id} reviews MUST be a list")
    if len(value) > MAX_REVIEWS_PER_CASE:
        raise CohortCorpusError(f"case {case_id} declares more than {MAX_REVIEWS_PER_CASE} reviews")
    records: list[CandidateReviewRecord] = []
    for review in value:
        if not isinstance(review, dict):
            raise CohortCorpusError(f"case {case_id} review MUST be a JSON object")
        _require_exact_keys(f"case {case_id} review", review, _REVIEW_KEYS)
        decision = _enum(ReviewDecision, _text(review, "decision"), "review decision")
        reviewed_at = _timestamp(review, "reviewed_at", case_id)
        evidence = _strings(review, "evidence_digests", case_id, MAX_EVIDENCE_ITEMS)
        reviewer = _text(review, "reviewer_principal")
        auth_digest = _text(review, "authentication_evidence_digest")
        review_id = content_digest(
            {
                "candidate_id": candidate_id,
                "reviewer_principal": reviewer,
                "decision": decision.value,
                "reviewed_at": instant(reviewed_at),
                "authentication_evidence_digest": auth_digest,
                "evidence_digests": sorted(evidence),
            }
        )
        records.append(
            CandidateReviewRecord(
                review_id=review_id,
                candidate_id=candidate_id,
                reviewer_principal=reviewer,
                decision=decision,
                reviewed_at=reviewed_at,
                authentication_evidence_digest=auth_digest,
                evidence_digests=evidence,
            )
        )
    return tuple(records)


def _external_denial(value: object, case_id: str) -> CohortExternalDenialInput | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CohortCorpusError(f"case {case_id} external_denial MUST be a JSON object or null")
    _require_exact_keys(f"case {case_id} external_denial", value, _DENIAL_KEYS)
    return CohortExternalDenialInput(
        reason=_enum(DenialReason, _text(value, "reason"), "denial reason"),
        detail=_text(value, "detail"),
        actor_ref=_text(value, "actor_ref"),
        authentication_evidence_digest=_text(value, "authentication_evidence_digest"),
        occurred_at=_timestamp(value, "occurred_at", case_id),
    )


__all__ = [
    "CORPUS_SCHEMA_VERSION",
    "LOCAL_EVIDENCE_CLASS",
    "LOCAL_VENUE",
    "MAX_CASES",
    "MAX_CORPUS_BYTES",
    "CohortCorpusError",
    "DecodedCorpus",
    "decode_corpus_document",
]
