"""Neutral contracts for review-only stewardship handover drafts."""

from __future__ import annotations

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
    source: Literal["deterministic"] = "deterministic"
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


class HandoverDraftArtifact(HandoverContract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    upload_id: UUID
    document_id: UUID
    version_id: UUID
    draft: StewardshipDraft
    yaml: str

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible API projection."""
        return self.model_dump(mode="json")


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
