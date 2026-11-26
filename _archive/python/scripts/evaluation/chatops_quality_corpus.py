"""Pure contract and coverage checks for a hidden ChatOps corpus manifest."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
)

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MIN_TURNS = 500
_MIN_TURNS_PER_LOCALE = 250
_MIN_ADVERSARIAL_TURNS = 100
_MIN_MULTI_TURN_CONVERSATIONS = 150
_MIN_SRE_TURNS = 150
_MIN_ACTION_CHANNEL_ATTACHMENT_TURNS = 100


class CorpusManifestError(ValueError):
    """A hidden corpus manifest failed its public metadata contract."""


class Locale(StrEnum):
    EN = "en"
    KO = "ko"


class CoverageTag(StrEnum):
    ADVERSARIAL_AMBIGUOUS = "adversarial_ambiguous"
    MULTI_TURN = "multi_turn"
    SRE_INCIDENT_RCA = "sre_incident_rca"
    ACTION_CHANNEL_ATTACHMENT = "action_channel_attachment"


@dataclass(frozen=True, slots=True)
class ReviewProtocol:
    labeling_protocol_version: str
    evaluator_set_version: str
    run_configuration_version: str
    confidence_method: str
    confidence_level: float
    minimum_point_success_rate: float
    minimum_independent_raters: int
    minimum_rater_agreement: float
    tie_break_protocol_version: str
    minimum_runs: int

    def __post_init__(self) -> None:
        for field, value in (
            ("labeling_protocol_version", self.labeling_protocol_version),
            ("evaluator_set_version", self.evaluator_set_version),
            ("run_configuration_version", self.run_configuration_version),
            ("confidence_method", self.confidence_method),
            ("tie_break_protocol_version", self.tie_break_protocol_version),
        ):
            _token(value, field)
        if not _finite_in(self.confidence_level, minimum=0.95, maximum=1.0):
            raise CorpusManifestError("confidence_level MUST be in [0.95, 1.0)")
        if not _finite_in(
            self.minimum_point_success_rate,
            minimum=0.98,
            maximum=1.0,
            include_maximum=True,
        ):
            raise CorpusManifestError("minimum_point_success_rate MUST be in [0.98, 1.0]")
        if type(self.minimum_independent_raters) is not int:
            raise CorpusManifestError("minimum_independent_raters MUST be an integer")
        if self.minimum_independent_raters < 2:
            raise CorpusManifestError("minimum_independent_raters MUST be at least 2")
        if not _finite_in(
            self.minimum_rater_agreement,
            minimum=0.8,
            maximum=1.0,
            include_maximum=True,
        ):
            raise CorpusManifestError("minimum_rater_agreement MUST be in [0.8, 1.0]")
        if type(self.minimum_runs) is not int:
            raise CorpusManifestError("minimum_runs MUST be an integer")
        if self.minimum_runs < CHATOPS_QUALITY_CONTRACT_V1.minimum_runs:
            raise CorpusManifestError("minimum_runs MUST satisfy the qualification contract")


@dataclass(frozen=True, slots=True)
class HiddenCorpusCase:
    case_id: str
    conversation_id: str
    turn_index: int
    locale: Locale
    content_commitment: str
    label_commitment: str
    tags: tuple[CoverageTag, ...]
    rubric_item_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.locale, Locale):
            raise CorpusManifestError("locale MUST be en or ko")
        _token(self.case_id, "case_id")
        _token(self.conversation_id, "conversation_id")
        if not self.case_id.startswith(f"{self.locale.value}-"):
            raise CorpusManifestError("case_id MUST start with its locale")
        if not self.conversation_id.startswith(f"{self.locale.value}-"):
            raise CorpusManifestError("conversation_id MUST start with its locale")
        if type(self.turn_index) is not int or self.turn_index < 1:
            raise CorpusManifestError("turn_index MUST be a positive integer")
        _digest(self.content_commitment, "content_commitment")
        _digest(self.label_commitment, "label_commitment")
        if any(not isinstance(tag, CoverageTag) for tag in self.tags):
            raise CorpusManifestError("tags MUST contain supported coverage tags")
        if self.tags != tuple(tag for tag in CoverageTag if tag in self.tags):
            raise CorpusManifestError("tags MUST be unique and in canonical order")
        if any(type(item_id) is not int for item_id in self.rubric_item_ids):
            raise CorpusManifestError("rubric_item_ids MUST contain integers")
        if not self.rubric_item_ids or self.rubric_item_ids != tuple(
            sorted(set(self.rubric_item_ids))
        ):
            raise CorpusManifestError("rubric_item_ids MUST be unique and in ascending order")
        if self.rubric_item_ids[0] < 1 or self.rubric_item_ids[-1] > 50:
            raise CorpusManifestError("rubric_item_ids MUST be in [1, 50]")


@dataclass(frozen=True, slots=True)
class HiddenCorpusManifest:
    corpus_id: str
    corpus_version: str
    frozen_at: str
    freeze_revision: str
    qualification_contract_version: str
    qualification_contract_digest: str
    restricted_artifact_id: str
    hidden_payload_digest: str
    review_protocol: ReviewProtocol
    rubric_observation_floors: tuple[int, ...]
    cases: tuple[HiddenCorpusCase, ...]

    def __post_init__(self) -> None:
        _token(self.corpus_id, "corpus_id")
        _token(self.corpus_version, "corpus_version")
        _timestamp(self.frozen_at, "frozen_at")
        _revision(self.freeze_revision, "freeze_revision")
        _token(self.restricted_artifact_id, "restricted_artifact_id")
        _digest(self.hidden_payload_digest, "hidden_payload_digest")
        contract = CHATOPS_QUALITY_CONTRACT_V1
        if (
            self.qualification_contract_version != contract.version
            or self.qualification_contract_digest != contract.content_digest
        ):
            raise CorpusManifestError(
                "qualification contract does not match the installed contract"
            )
        if len(self.rubric_observation_floors) != 50:
            raise CorpusManifestError("rubric_observation_floors MUST define item ids 1 through 50")
        if any(type(value) is not int or value < 1 for value in self.rubric_observation_floors):
            raise CorpusManifestError("rubric observation floors MUST be positive integers")
        _validate_coverage(self)

    @property
    def content_digest(self) -> str:
        canonical = json.dumps(
            manifest_payload(self),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


def _validate_coverage(manifest: HiddenCorpusManifest) -> None:
    cases = manifest.cases
    if len(cases) < _MIN_TURNS:
        raise CorpusManifestError(f"corpus MUST contain at least {_MIN_TURNS} turns")
    if len({case.case_id for case in cases}) != len(cases):
        raise CorpusManifestError("case_id values MUST be unique")
    if len({case.content_commitment for case in cases}) != len(cases):
        raise CorpusManifestError("content_commitment values MUST be unique")

    locale_counts = Counter(case.locale for case in cases)
    if locale_counts[Locale.EN] != locale_counts[Locale.KO]:
        raise CorpusManifestError("English and Korean turn counts MUST be equal")
    if any(locale_counts[locale] < _MIN_TURNS_PER_LOCALE for locale in Locale):
        raise CorpusManifestError("each locale MUST contain at least 250 turns")

    conversations: dict[str, list[HiddenCorpusCase]] = defaultdict(list)
    for case in cases:
        conversations[case.conversation_id].append(case)
    multi_turn_conversations = 0
    for conversation_id, turns in conversations.items():
        ordered = sorted(turns, key=lambda turn: turn.turn_index)
        if len({turn.locale for turn in ordered}) != 1:
            raise CorpusManifestError(f"conversation {conversation_id} MUST use one locale")
        if tuple(turn.turn_index for turn in ordered) != tuple(range(1, len(ordered) + 1)):
            raise CorpusManifestError(
                f"conversation {conversation_id} turn indexes MUST be consecutive"
            )
        tagged = [CoverageTag.MULTI_TURN in turn.tags for turn in ordered]
        if len(ordered) >= 2:
            if not all(tagged):
                raise CorpusManifestError(
                    f"conversation {conversation_id} MUST tag every multi-turn case"
                )
            multi_turn_conversations += 1
        elif any(tagged):
            raise CorpusManifestError(
                f"conversation {conversation_id} cannot tag a single turn as multi-turn"
            )
    if multi_turn_conversations < _MIN_MULTI_TURN_CONVERSATIONS:
        raise CorpusManifestError("corpus MUST contain at least 150 multi-turn conversations")

    _require_tagged_turns(
        cases,
        CoverageTag.ADVERSARIAL_AMBIGUOUS,
        _MIN_ADVERSARIAL_TURNS,
    )
    _require_tagged_turns(
        cases,
        CoverageTag.SRE_INCIDENT_RCA,
        _MIN_SRE_TURNS,
    )
    _require_tagged_turns(
        cases,
        CoverageTag.ACTION_CHANNEL_ATTACHMENT,
        _MIN_ACTION_CHANNEL_ATTACHMENT_TURNS,
    )
    observation_counts = Counter(item_id for case in cases for item_id in case.rubric_item_ids)
    deficient = [
        item_id
        for item_id, floor in enumerate(manifest.rubric_observation_floors, start=1)
        if observation_counts[item_id] < floor
    ]
    if deficient:
        raise CorpusManifestError(
            "rubric observation floors are unmet for item ids "
            + ",".join(str(item_id) for item_id in deficient)
        )


def _require_tagged_turns(
    cases: tuple[HiddenCorpusCase, ...],
    tag: CoverageTag,
    minimum: int,
) -> None:
    count = sum(tag in case.tags for case in cases)
    if count < minimum:
        raise CorpusManifestError(f"{tag.value} MUST contain at least {minimum} turns")


def summary(manifest: HiddenCorpusManifest) -> dict[str, object]:
    """Return bounded coverage metadata without hidden prompts or labels."""

    locale_counts = Counter(case.locale for case in manifest.cases)
    conversations = Counter(case.conversation_id for case in manifest.cases)
    observation_counts = Counter(
        item_id for case in manifest.cases for item_id in case.rubric_item_ids
    )
    return {
        "schema_version": "1.0.0",
        "evidence_kind": "hidden_chatops_corpus_manifest_summary",
        "corpus_id": manifest.corpus_id,
        "corpus_version": manifest.corpus_version,
        "content_digest": manifest.content_digest,
        "frozen_at": manifest.frozen_at,
        "freeze_revision": manifest.freeze_revision,
        "restricted_artifact_id": manifest.restricted_artifact_id,
        "hidden_payload_digest": manifest.hidden_payload_digest,
        "qualification_contract_version": manifest.qualification_contract_version,
        "qualification_contract_digest": manifest.qualification_contract_digest,
        "turn_count": len(manifest.cases),
        "locales": {locale.value: locale_counts[locale] for locale in Locale},
        "tagged_turns": {
            tag.value: sum(tag in case.tags for case in manifest.cases)
            for tag in CoverageTag
            if tag is not CoverageTag.MULTI_TURN
        },
        "multi_turn_conversations": sum(count >= 2 for count in conversations.values()),
        "rubric_observation_counts": {
            str(item_id): observation_counts[item_id] for item_id in range(1, 51)
        },
        "rubric_observation_floors": {
            str(item_id): manifest.rubric_observation_floors[item_id - 1]
            for item_id in range(1, 51)
        },
        "review_protocol": review_protocol_payload(manifest.review_protocol),
    }


def manifest_payload(manifest: HiddenCorpusManifest) -> dict[str, object]:
    """Return the canonical metadata used to content-address the manifest."""

    return {
        "schema_version": 1,
        "corpus_id": manifest.corpus_id,
        "corpus_version": manifest.corpus_version,
        "frozen_at": manifest.frozen_at,
        "freeze_revision": manifest.freeze_revision,
        "qualification_contract_version": manifest.qualification_contract_version,
        "qualification_contract_digest": manifest.qualification_contract_digest,
        "restricted_artifact_id": manifest.restricted_artifact_id,
        "hidden_payload_digest": manifest.hidden_payload_digest,
        "review_protocol": review_protocol_payload(manifest.review_protocol),
        "rubric_observation_floors": {
            str(item_id): manifest.rubric_observation_floors[item_id - 1]
            for item_id in range(1, 51)
        },
        "cases": [
            {
                "case_id": case.case_id,
                "conversation_id": case.conversation_id,
                "turn_index": case.turn_index,
                "locale": case.locale.value,
                "content_commitment": case.content_commitment,
                "label_commitment": case.label_commitment,
                "tags": [tag.value for tag in case.tags],
                "rubric_item_ids": list(case.rubric_item_ids),
            }
            for case in manifest.cases
        ],
    }


def review_protocol_payload(protocol: ReviewProtocol) -> dict[str, object]:
    return {
        "labeling_protocol_version": protocol.labeling_protocol_version,
        "evaluator_set_version": protocol.evaluator_set_version,
        "run_configuration_version": protocol.run_configuration_version,
        "confidence_method": protocol.confidence_method,
        "confidence_level": protocol.confidence_level,
        "minimum_point_success_rate": protocol.minimum_point_success_rate,
        "minimum_independent_raters": protocol.minimum_independent_raters,
        "minimum_rater_agreement": protocol.minimum_rater_agreement,
        "tie_break_protocol_version": protocol.tie_break_protocol_version,
        "minimum_runs": protocol.minimum_runs,
    }


def _token(value: str, field: str) -> None:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise CorpusManifestError(f"{field} MUST be a bounded portable token")


def _digest(value: str, field: str) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise CorpusManifestError(f"{field} MUST be a lowercase SHA-256 digest")


def _revision(value: str, field: str) -> None:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise CorpusManifestError(f"{field} MUST be a full lowercase git object id")


def _timestamp(value: str, field: str) -> None:
    if not isinstance(value, str):
        raise CorpusManifestError(f"{field} MUST be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CorpusManifestError(f"{field} MUST be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise CorpusManifestError(f"{field} MUST include a timezone")


def _finite_in(
    value: float,
    *,
    minimum: float,
    maximum: float,
    include_maximum: bool = False,
) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    upper = value <= maximum if include_maximum else value < maximum
    return math.isfinite(value) and minimum <= value and upper


__all__ = [
    "CorpusManifestError",
    "CoverageTag",
    "HiddenCorpusCase",
    "HiddenCorpusManifest",
    "Locale",
    "ReviewProtocol",
    "manifest_payload",
    "review_protocol_payload",
    "summary",
]
