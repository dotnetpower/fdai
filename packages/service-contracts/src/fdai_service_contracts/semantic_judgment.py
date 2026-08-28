"""Shared no-authority contracts for natural-language semantic judgment."""

from __future__ import annotations

import math
import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from fdai_service_contracts.ontology_query import QueryContract, content_digest

Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
MachineToken = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")]
CanonicalIdentity = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,255}$")]
_LINK_LIKE_TEXT = re.compile(r"\b[a-z0-9](?:[a-z0-9-]{0,62})\.[a-z]{2,63}\b", re.IGNORECASE)
_KOREAN_POLITE_ENDINGS = ("요", "니다", "세요", "까요", "십시오", "죠")
_KOREAN_POLITE_STANDALONES = frozenset({"네", "예"})


class SemanticDiscourseMode(StrEnum):
    """How the utterance presents the requested meaning."""

    DIRECT = "direct"
    HYPOTHETICAL = "hypothetical"
    QUOTED = "quoted"


class SemanticJudgmentDisposition(StrEnum):
    """Terminal status of one verified semantic judgment."""

    ACCEPTED = "accepted"
    CLARIFICATION = "clarification"
    AMBIGUOUS = "ambiguous"
    LOW_CONFIDENCE = "low_confidence"
    UNAVAILABLE = "unavailable"
    MALFORMED = "malformed"


class SemanticJudgmentTier(StrEnum):
    """Model-backed tier that produced the accepted proposal."""

    T1 = "t1"
    T2 = "t2"


class SemanticTarget(QueryContract):
    """One source-grounded entity or target proposed from bounded text."""

    kind: MachineToken
    value: Annotated[str, Field(min_length=1, max_length=256)]
    canonical_value: CanonicalIdentity | None = None
    source_start: Annotated[int, Field(ge=0, le=32_000)]
    source_end: Annotated[int, Field(gt=0, le=32_000)]

    @model_validator(mode="after")
    def _span_is_ordered(self) -> SemanticTarget:
        if self.source_end <= self.source_start:
            raise ValueError("semantic target source span MUST be ordered")
        return self


class SemanticDirectResponseDraft(QueryContract):
    """One bounded model-authored social response without operational authority."""

    locale: Literal["en", "ko"]
    answer: Annotated[str, Field(min_length=1, max_length=768)]
    profile_digest: Digest
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _answer_is_bounded_plain_text(self) -> SemanticDirectResponseDraft:
        if self.answer != self.answer.strip():
            raise ValueError("semantic direct response answer MUST be trimmed")
        if "\r" in self.answer or "\n" in self.answer:
            raise ValueError("semantic direct response answer MUST be one paragraph")
        if (
            "://" in self.answer
            or _LINK_LIKE_TEXT.search(self.answer) is not None
            or any(char in self.answer for char in r"<>\[\]`*_#~|{}")
        ):
            raise ValueError("semantic direct response answer MUST NOT contain links or markup")
        if self.locale == "ko":
            sentences = tuple(
                sentence.strip().rstrip("\"')]} ")
                for sentence in re.split(r"[.!?。！？]+", self.answer)
                if sentence.strip()
            )
            if not sentences or any(
                sentence not in _KOREAN_POLITE_STANDALONES
                and not sentence.endswith(_KOREAN_POLITE_ENDINGS)
                for sentence in sentences
            ):
                raise ValueError(
                    "Korean semantic direct response MUST use polite honorific endings"
                )
        return self


class SemanticJudgmentProposal(QueryContract):
    """Untrusted structured meaning proposed without policy or action authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    primary_intent: MachineToken
    secondary_intents: Annotated[tuple[MachineToken, ...], Field(max_length=8)] = ()
    targets: Annotated[tuple[SemanticTarget, ...], Field(max_length=32)] = ()
    requested_facets: Annotated[tuple[MachineToken, ...], Field(max_length=32)] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    ambiguous: bool
    alternatives: Annotated[tuple[MachineToken, ...], Field(max_length=8)] = ()
    unresolved_terms: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=128)], ...],
        Field(max_length=8),
    ] = ()
    clarification: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    direct_response: SemanticDirectResponseDraft | None = None
    discourse_mode: SemanticDiscourseMode = SemanticDiscourseMode.DIRECT
    action_posture: Literal["advise_only", "draft_only"] = "advise_only"
    action_subject: Literal["none", "ActionType", "Change", "Incident", "RecoveryPlan", "Rule"]
    authority: Literal["candidate_only"] = "candidate_only"
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _meaning_is_consistent(self) -> SemanticJudgmentProposal:
        if not math.isfinite(self.confidence):
            raise ValueError("semantic judgment confidence MUST be finite")
        for name, values in (
            ("secondary_intents", self.secondary_intents),
            ("requested_facets", self.requested_facets),
            ("alternatives", self.alternatives),
            ("unresolved_terms", self.unresolved_terms),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"semantic judgment {name} MUST be unique")
        if self.primary_intent in self.secondary_intents:
            raise ValueError("primary semantic intent MUST NOT be duplicated")
        if self.ambiguous != bool(self.alternatives or self.unresolved_terms):
            raise ValueError("semantic judgment ambiguity MUST match its unresolved meaning")
        if (self.clarification is not None) != self.ambiguous:
            raise ValueError("ambiguous semantic judgment MUST carry one clarification")
        if self.clarification is not None and (
            "\n" in self.clarification
            or "\r" in self.clarification
            or not self.clarification.endswith("?")
        ):
            raise ValueError("semantic judgment clarification MUST be one question")
        if (self.action_posture == "draft_only") != (self.action_subject != "none"):
            raise ValueError("semantic judgment action subject MUST match draft posture")
        direct_intent = self.primary_intent in {"greeting", "self_introduction"}
        if direct_intent != (self.direct_response is not None):
            raise ValueError(
                "semantic direct response intent MUST carry exactly one model-authored answer"
            )
        if self.direct_response is not None and (
            self.ambiguous or self.action_posture != "advise_only" or self.action_subject != "none"
        ):
            raise ValueError("semantic direct response answer MUST remain unambiguous and advisory")
        return self

    @property
    def proposal_digest(self) -> str:
        """Return the replay-stable digest of this candidate-only proposal."""

        return content_digest(self.model_dump(mode="json"))


class SemanticJudgmentReceipt(QueryContract):
    """Content-free provenance for one terminal semantic judgment."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    input_digest: Digest
    context_digest: Digest
    capability_digest: Digest
    proposal_digest: Digest | None = None
    profile_id: MachineToken
    profile_version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    tier: SemanticJudgmentTier | None = None
    model_config_digest: Digest | None = None
    prompt_digest: Digest | None = None
    disposition: SemanticJudgmentDisposition
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    ambiguous: bool
    latency_ms: Annotated[int, Field(ge=0, le=120_000)]
    reason_code: MachineToken
    execution_authority: Literal[False] = False
    receipt_digest: Digest

    @model_validator(mode="after")
    def _receipt_is_consistent(self) -> SemanticJudgmentReceipt:
        if self.confidence is not None and not math.isfinite(self.confidence):
            raise ValueError("semantic judgment receipt confidence MUST be finite")
        accepted = self.disposition is SemanticJudgmentDisposition.ACCEPTED
        model_bound = (
            self.tier,
            self.model_config_digest,
            self.prompt_digest,
            self.proposal_digest,
            self.confidence,
        )
        if accepted and any(value is None for value in model_bound):
            raise ValueError("accepted semantic judgment MUST carry complete model provenance")
        if (
            not accepted
            and self.disposition
            in {
                SemanticJudgmentDisposition.UNAVAILABLE,
                SemanticJudgmentDisposition.MALFORMED,
            }
            and any(value is not None for value in model_bound)
        ):
            raise ValueError("failed semantic judgment MUST NOT claim an accepted proposal")
        body = self.model_dump(mode="json", exclude={"receipt_digest"})
        if self.receipt_digest != content_digest(body):
            raise ValueError("semantic judgment receipt digest does not match its content")
        return self


__all__ = [
    "SemanticDirectResponseDraft",
    "SemanticDiscourseMode",
    "SemanticJudgmentDisposition",
    "SemanticJudgmentProposal",
    "SemanticJudgmentReceipt",
    "SemanticJudgmentTier",
    "SemanticTarget",
]
