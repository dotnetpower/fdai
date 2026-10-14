"""Neutral contracts for review-only stewardship handover drafts."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class HandoverContract(BaseModel):
    """Immutable validated base for cross-service handover records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class StewardKind(StrEnum):
    USER = "user"
    GROUP = "group"


class StewardResponsibility(StrEnum):
    ACCOUNTABLE = "accountable"
    INFORMED = "informed"


class StewardDuty(StrEnum):
    PRIMARY = "primary"
    BACKUP = "backup"
    ESCALATION = "escalation"


class StewardshipSubject(HandoverContract):
    """One existing service-owned stewardship binding retained in a draft."""

    kind: StewardKind
    oid: Annotated[str, Field(min_length=1, max_length=256)]
    responsibility: StewardResponsibility
    duty: StewardDuty | None = None

    @model_validator(mode="after")
    def _validate_duty(self) -> StewardshipSubject:
        if self.responsibility is StewardResponsibility.INFORMED and self.duty is not None:
            raise ValueError("informed stewardship subjects MUST NOT declare a duty")
        return self


class StewardshipAgentInput(HandoverContract):
    """Current bindings for one agent as observed by the worker service."""

    agent_name: Annotated[str, Field(min_length=1, max_length=64)]
    stewards: tuple[StewardshipSubject, ...] = ()
    accept_autonomous_reason: Annotated[str, Field(min_length=1, max_length=512)] | None = None


class StewardshipInput(HandoverContract):
    """Bounded current stewardship state used only as a draft-generation baseline."""

    version: Literal[1, 2]
    revision: Annotated[str, Field(min_length=1, max_length=128)]
    maintainers: Annotated[tuple[str, ...], Field(min_length=1, max_length=32)]
    agents: Annotated[tuple[StewardshipAgentInput, ...], Field(max_length=64)] = ()
    hop_timeout_seconds: Annotated[int, Field(ge=1, le=86_400)] = 900
    over_assigned_max: Annotated[int, Field(ge=1, le=100)] = 5

    @model_validator(mode="after")
    def _validate_unique_agents(self) -> StewardshipInput:
        names = tuple(item.agent_name.casefold() for item in self.agents)
        if len(names) != len(set(names)):
            raise ValueError("stewardship input agent names MUST be unique")
        return self


class HandoverDraftOutcome(StrEnum):
    DRAFTED = "drafted"
    ABSTAINED = "abstained"


class ResolvedStewardIdentity(HandoverContract):
    oid: Annotated[str, Field(min_length=1, max_length=256)]
    kind: StewardKind = StewardKind.USER


class HandoverSourceSpan(HandoverContract):
    doc_id: Annotated[str, Field(min_length=1, max_length=128)]
    line: Annotated[int, Field(ge=1)]
    quote: Annotated[str, Field(min_length=1, max_length=200)]


class HandoverPerson(HandoverContract):
    display_name: Annotated[str, Field(min_length=1, max_length=128)]
    kind: StewardKind = StewardKind.USER
    oid: Annotated[str, Field(min_length=1, max_length=256)] | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unresolved(self) -> bool:
        return self.oid is None


class HandoverMapping(HandoverContract):
    agent_name: Annotated[str, Field(min_length=1, max_length=64)]
    person: HandoverPerson
    responsibility: StewardResponsibility
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    source: Literal["deterministic", "model"] = "deterministic"
    citations: Annotated[tuple[HandoverSourceSpan, ...], Field(min_length=1)]
    rationale: Annotated[str, Field(max_length=256)] = ""


class StewardshipDraft(HandoverContract):
    version: Annotated[int, Field(ge=1)] = 1
    outcome: HandoverDraftOutcome
    mappings: tuple[HandoverMapping, ...] = ()
    abstained: tuple[HandoverMapping, ...] = ()
    unresolved_people: tuple[HandoverPerson, ...] = ()
    unmapped_agents: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class HandoverModelReview(HandoverContract):
    author_identity: Annotated[str, Field(min_length=1, max_length=256)]
    reviewer_identity: Annotated[str, Field(min_length=1, max_length=256)]
    source_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    proposal_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    reviewed_mapping_count: Annotated[int, Field(strict=True, ge=1, le=2_000)]
    prompt_tokens: Annotated[int, Field(strict=True, ge=0)] = 0
    completion_tokens: Annotated[int, Field(strict=True, ge=0)] = 0
    cost_micros: Annotated[int, Field(strict=True, ge=0)] = 0
    pricing_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None
    model_calls: Literal[2] = 2
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _independent_review(self) -> HandoverModelReview:
        if (
            not self.author_identity.strip()
            or not self.reviewer_identity.strip()
            or self.author_identity.strip().casefold() == self.reviewer_identity.strip().casefold()
        ):
            raise ValueError("handover model author and reviewer MUST be independent")
        return self


def handover_model_proposal_digest(mappings: tuple[HandoverMapping, ...]) -> str:
    normalized: list[dict[str, object]] = []
    for mapping in mappings:
        body = mapping.model_dump(mode="json", exclude_computed_fields=True)
        body["person"]["oid"] = None
        normalized.append(body)
    normalized.sort(key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    return hashlib.sha256(
        json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


class HandoverDraftArtifact(HandoverContract):
    schema_version: Literal["1.0.0", "1.1.0"] = "1.0.0"
    upload_id: UUID
    document_id: UUID
    version_id: UUID
    draft: StewardshipDraft
    yaml: str
    model_review: HandoverModelReview | None = Field(
        default=None,
        exclude_if=lambda review: review is None,
    )

    @model_validator(mode="after")
    def _model_source_is_explicit(self) -> HandoverDraftArtifact:
        mappings = (*self.draft.mappings, *self.draft.abstained)
        authored = tuple(mapping for mapping in mappings if mapping.source == "model")
        if authored and (self.schema_version != "1.1.0" or self.model_review is None):
            raise ValueError("model handover mappings require version 1.1 and independent review")
        if self.model_review is not None and (
            self.schema_version != "1.1.0"
            or self.model_review.reviewed_mapping_count != len(authored)
            or self.model_review.proposal_sha256 != handover_model_proposal_digest(authored)
        ):
            raise ValueError("handover model review MUST cover every exact model mapping")
        return self

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible API projection."""
        return self.model_dump(mode="json", exclude_computed_fields=True)


def handover_governance_idempotency_key(artifact: HandoverDraftArtifact) -> str:
    """Return the stable review-delivery key for one handover draft."""

    digest = hashlib.sha256()
    for part in (
        str(artifact.upload_id),
        str(artifact.document_id),
        str(artifact.version_id),
        artifact.yaml,
    ):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x1f")
    return f"stewardship-handover:{digest.hexdigest()}"


class StewardshipMergeRecord(HandoverContract):
    """Validated merge evidence emitted by a signed stewardship webhook."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    delivery_id: Annotated[str, Field(min_length=1, max_length=256)]
    pr_ref: Annotated[str, Field(min_length=1, max_length=256)]
    actor_identity: Annotated[str, Field(min_length=1, max_length=256)]
    merge_commit_sha: Annotated[str, Field(min_length=1, max_length=128)]
    merged_yaml: Annotated[str, Field(min_length=1, max_length=2_000_000)]


class RepositoryHandoverDraft(HandoverContract):
    """Authenticated repository input that remains inert until separate human review."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    delivery_id: Annotated[str, Field(min_length=1, max_length=256)]
    repository: Annotated[str, Field(min_length=3, max_length=256)]
    actor_identity: Annotated[str, Field(min_length=1, max_length=256)]
    source_ref: Annotated[str, Field(min_length=1, max_length=512)]
    content: Annotated[str, Field(min_length=1, max_length=65_536)]
    content_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    mode: Literal["shadow"] = "shadow"
    may_merge: Literal[False] = False
    may_execute: Literal[False] = False
