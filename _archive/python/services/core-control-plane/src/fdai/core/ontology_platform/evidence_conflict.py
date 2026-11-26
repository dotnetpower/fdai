"""Immutable evidence-conflict revisions and never-raising action matching."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, model_validator

from fdai.core.mscp_profile import MscpAuthorityCeiling
from fdai.core.ontology_platform.functions import ontology_function_digest
from fdai.core.ontology_platform.observation_adjudication import (
    CrossSourceStateAdjudication,
    CrossSourceStateStatus,
    StateEvidenceSnapshot,
)
from fdai.shared.contracts.models import ContractBase, OntologyActionType
from fdai.shared.providers.state_evidence import StateFactAuthority

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_CONFLICT_ID_PATTERN = r"^evidence-conflict:[a-f0-9]{64}$"
_REVISION_PATTERN = r"^evidence-conflict-revision:[a-f0-9]{64}$"
_SLOT_PATTERN = r"^evidence-conflict-slot:[a-f0-9]{64}$"
_SEMANTIC_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
_MAX_REF_LENGTH = 512
_Ref = Annotated[str, Field(min_length=1, max_length=_MAX_REF_LENGTH)]


class EvidenceConflictStatus(StrEnum):
    """Lifecycle status for one immutable conflict revision."""

    ACTIVE = "active"
    RESOLVED = "resolved"


class EvidenceConflictDisposition(StrEnum):
    """Never-raising action match result."""

    NOT_APPLICABLE = "not_applicable"
    ACTIVE_CONFLICT = "active_conflict"
    EXPIRED_UNRESOLVED = "expired_unresolved"


class EvidenceSourceLineage(ContractBase):
    """Bounded source identity and freshness used by one adjudication."""

    source_identity: _Ref
    source_revision: _Ref
    claim_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    authority: StateFactAuthority
    evidence_cutoff: datetime
    recorded_at: datetime
    freshness_ceiling_seconds: Annotated[int, Field(ge=1)]
    evidence_refs: tuple[_Ref, ...]

    @model_validator(mode="after")
    def _validate_lineage(self) -> EvidenceSourceLineage:
        if self.evidence_cutoff.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("evidence-conflict source timestamps MUST be timezone-aware")
        if self.evidence_cutoff > self.recorded_at:
            raise ValueError("evidence-conflict cutoff MUST NOT exceed recorded time")
        if not self.evidence_refs or tuple(sorted(set(self.evidence_refs))) != self.evidence_refs:
            raise ValueError("evidence-conflict refs MUST be non-empty, unique, and sorted")
        return self


class EvidenceConflictRevision(ContractBase):
    """Heimdall-owned immutable revision for one exact target-generation slot."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    id: Annotated[str, Field(pattern=_CONFLICT_ID_PATTERN)]
    slot_ref: Annotated[str, Field(pattern=_SLOT_PATTERN)]
    revision_ref: Annotated[str, Field(pattern=_REVISION_PATTERN)]
    kind: Literal["cross_source_state"] = "cross_source_state"
    status: EvidenceConflictStatus
    target_ref: _Ref
    scope_ref: _Ref
    generation_ref: _Ref
    semantic_refs: tuple[Annotated[str, Field(pattern=_SEMANTIC_PATTERN)], ...]
    conflicting_fields: tuple[_Ref, ...]
    source_a: EvidenceSourceLineage
    source_b: EvidenceSourceLineage
    evidence_cutoff: datetime
    expires_at: datetime
    supersedes_revision_ref: Annotated[str, Field(pattern=_REVISION_PATTERN)] | None = None
    producer_principal: Literal["Heimdall"] = "Heimdall"
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False

    @classmethod
    def create(
        cls,
        *,
        status: EvidenceConflictStatus,
        target_ref: str,
        scope_ref: str,
        generation_ref: str,
        semantic_refs: tuple[str, ...],
        conflicting_fields: tuple[str, ...],
        source_a: EvidenceSourceLineage,
        source_b: EvidenceSourceLineage,
        supersedes_revision_ref: str | None,
    ) -> Self:
        """Create a stable slot identity and content-addressed revision."""

        slot_material = {
            "kind": "cross_source_state",
            "target_ref": target_ref,
            "scope_ref": scope_ref,
            "generation_ref": generation_ref,
        }
        slot_digest = ontology_function_digest(slot_material).removeprefix("sha256:")
        slot_ref = f"evidence-conflict-slot:{slot_digest}"
        conflict_id = f"evidence-conflict:{slot_digest}"
        evidence_cutoff = max(
            source_a.evidence_cutoff,
            source_b.evidence_cutoff,
        ).astimezone(UTC)
        expires_at = min(_expires_at(source_a), _expires_at(source_b))
        prototype = cls.model_construct(
            schema_version="1.0.0",
            id=conflict_id,
            slot_ref=slot_ref,
            revision_ref="evidence-conflict-revision:" + "0" * 64,
            kind="cross_source_state",
            status=status,
            target_ref=target_ref,
            scope_ref=scope_ref,
            generation_ref=generation_ref,
            semantic_refs=semantic_refs,
            conflicting_fields=conflicting_fields,
            source_a=source_a,
            source_b=source_b,
            evidence_cutoff=evidence_cutoff,
            expires_at=expires_at,
            supersedes_revision_ref=supersedes_revision_ref,
            producer_principal="Heimdall",
            execution_authority=False,
            mutation_authority=False,
        )
        material = prototype.model_dump(mode="json", exclude={"revision_ref"})
        digest = ontology_function_digest(material).removeprefix("sha256:")
        return cls.model_validate(
            {
                **material,
                "revision_ref": f"evidence-conflict-revision:{digest}",
            }
        )

    @model_validator(mode="after")
    def _validate_revision(self) -> EvidenceConflictRevision:
        if tuple(sorted(set(self.semantic_refs))) != self.semantic_refs or not self.semantic_refs:
            raise ValueError("evidence-conflict semantic refs MUST be non-empty and canonical")
        if tuple(sorted(set(self.conflicting_fields))) != self.conflicting_fields:
            raise ValueError("evidence-conflict fields MUST be sorted and unique")
        if self.status is EvidenceConflictStatus.ACTIVE and not self.conflicting_fields:
            raise ValueError("active evidence conflict MUST name conflicting fields")
        if self.status is EvidenceConflictStatus.RESOLVED and self.conflicting_fields:
            raise ValueError("resolved evidence conflict MUST NOT retain conflicting fields")
        if self.status is EvidenceConflictStatus.RESOLVED and self.supersedes_revision_ref is None:
            raise ValueError("resolved evidence conflict MUST supersede an active revision")
        if (
            self.status is EvidenceConflictStatus.RESOLVED
            and self.source_a.claim_digest != self.source_b.claim_digest
        ):
            raise ValueError("resolved evidence conflict requires agreeing source claims")
        if (
            self.status is EvidenceConflictStatus.ACTIVE
            and self.source_a.claim_digest == self.source_b.claim_digest
        ):
            raise ValueError("active evidence conflict requires disagreeing source claims")
        if self.source_a.source_identity == self.source_b.source_identity:
            raise ValueError("evidence conflict requires distinct source identities")
        if self.evidence_cutoff.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("evidence-conflict timestamps MUST be timezone-aware")
        if self.expires_at <= self.evidence_cutoff:
            raise ValueError("evidence-conflict expiry MUST follow its evidence cutoff")
        slot_material = {
            "kind": self.kind,
            "target_ref": self.target_ref,
            "scope_ref": self.scope_ref,
            "generation_ref": self.generation_ref,
        }
        slot_digest = ontology_function_digest(slot_material).removeprefix("sha256:")
        if self.slot_ref != f"evidence-conflict-slot:{slot_digest}":
            raise ValueError("evidence-conflict slot identity does not match")
        if self.id != f"evidence-conflict:{slot_digest}":
            raise ValueError("evidence-conflict object identity does not match")
        material = self.model_dump(mode="json", exclude={"revision_ref"})
        revision_digest = ontology_function_digest(material).removeprefix("sha256:")
        if self.revision_ref != f"evidence-conflict-revision:{revision_digest}":
            raise ValueError("evidence-conflict revision identity does not match")
        return self


class EvidenceConflictCurrentReader(Protocol):
    """Read unresolved current conflicts for one exact target and semantic set."""

    async def active_for(
        self,
        *,
        target_ref: str,
        semantic_refs: frozenset[str],
    ) -> tuple[EvidenceConflictRevision, ...]: ...

    async def current(self, slot_ref: str) -> EvidenceConflictRevision | None: ...


class EvidenceConflictSink(Protocol):
    """Append one Heimdall-owned revision to durable history and current state."""

    async def append(self, revision: EvidenceConflictRevision) -> bool: ...


class EvidenceConflictCandidatePublisher(Protocol):
    """Publish one deterministic candidate through typed event ingress."""

    async def publish(self, revision: EvidenceConflictRevision) -> None: ...


async def current_evidence_conflict_ceiling(
    reader: EvidenceConflictCurrentReader,
    *,
    action_type: OntologyActionType,
    target_ref: str,
    evaluated_at: datetime,
) -> tuple[
    MscpAuthorityCeiling,
    EvidenceConflictDisposition,
    tuple[EvidenceConflictRevision, ...],
]:
    """Read and reduce current conflicts for one exact ActionType dependency set."""

    required = frozenset(action_type.required_evidence_semantic_refs)
    if not required:
        return (
            MscpAuthorityCeiling.PRESERVE,
            EvidenceConflictDisposition.NOT_APPLICABLE,
            (),
        )
    conflicts = await reader.active_for(
        target_ref=target_ref,
        semantic_refs=required,
    )
    ceiling, disposition = evidence_conflict_ceiling(
        conflicts,
        action_type=action_type,
        target_ref=target_ref,
        evaluated_at=evaluated_at,
    )
    return ceiling, disposition, conflicts


def build_cross_source_evidence_conflict(
    adjudication: CrossSourceStateAdjudication,
    *,
    generation_ref: str,
    semantic_refs: tuple[str, ...],
    supersedes_revision_ref: str | None = None,
) -> EvidenceConflictRevision:
    """Translate an agreeing or conflicting comparison into one lifecycle revision."""

    telemetry = adjudication.telemetry
    if telemetry is None or adjudication.status not in {
        CrossSourceStateStatus.CONFLICTING,
        CrossSourceStateStatus.AGREED,
    }:
        raise ValueError("evidence conflict requires an agreeing or conflicting adjudication")
    projection_lineage = _lineage(adjudication.projection)
    telemetry_lineage = _lineage(telemetry)
    if projection_lineage.authority is not StateFactAuthority.PROVIDER:
        raise ValueError("evidence-conflict projection MUST use provider authority")
    if telemetry_lineage.authority is not StateFactAuthority.TELEMETRY:
        raise ValueError("evidence-conflict telemetry MUST use telemetry authority")
    status = (
        EvidenceConflictStatus.ACTIVE
        if adjudication.status is CrossSourceStateStatus.CONFLICTING
        else EvidenceConflictStatus.RESOLVED
    )
    return EvidenceConflictRevision.create(
        status=status,
        target_ref=adjudication.projection.target_id,
        scope_ref=adjudication.projection.scope_ref,
        generation_ref=generation_ref,
        semantic_refs=tuple(sorted(set(semantic_refs))),
        conflicting_fields=(
            tuple(sorted(set(adjudication.conflicting_fields)))
            if status is EvidenceConflictStatus.ACTIVE
            else ()
        ),
        source_a=projection_lineage,
        source_b=telemetry_lineage,
        supersedes_revision_ref=supersedes_revision_ref,
    )


def evidence_conflict_slot_ref(
    *,
    target_ref: str,
    scope_ref: str,
    generation_ref: str,
    kind: str = "cross_source_state",
) -> str:
    """Return the stable slot identity before a revision is constructed."""

    digest = ontology_function_digest(
        {
            "kind": kind,
            "target_ref": target_ref,
            "scope_ref": scope_ref,
            "generation_ref": generation_ref,
        }
    ).removeprefix("sha256:")
    return f"evidence-conflict-slot:{digest}"


def evidence_conflict_ceiling(
    conflicts: tuple[EvidenceConflictRevision, ...],
    *,
    action_type: OntologyActionType,
    target_ref: str,
    evaluated_at: datetime,
) -> tuple[MscpAuthorityCeiling, EvidenceConflictDisposition]:
    """Lower only an action whose canonical evidence requirements intersect."""

    if evaluated_at.tzinfo is None:
        raise ValueError("evidence-conflict evaluation time MUST be timezone-aware")
    required = frozenset(action_type.required_evidence_semantic_refs)
    matching = tuple(
        conflict
        for conflict in conflicts
        if conflict.status is EvidenceConflictStatus.ACTIVE
        and conflict.target_ref == target_ref
        and required.intersection(conflict.semantic_refs)
    )
    if not matching:
        return MscpAuthorityCeiling.PRESERVE, EvidenceConflictDisposition.NOT_APPLICABLE
    if any(
        evaluated_at.astimezone(UTC) > conflict.expires_at.astimezone(UTC) for conflict in matching
    ):
        return MscpAuthorityCeiling.HOLD, EvidenceConflictDisposition.EXPIRED_UNRESOLVED
    return MscpAuthorityCeiling.HOLD, EvidenceConflictDisposition.ACTIVE_CONFLICT


def _lineage(snapshot: StateEvidenceSnapshot) -> EvidenceSourceLineage:
    metadata = snapshot.metadata
    return EvidenceSourceLineage(
        source_identity=metadata.source_identity,
        source_revision=metadata.source_revision,
        claim_digest=ontology_function_digest(
            {
                "target_ref": snapshot.target_id,
                "scope_ref": snapshot.scope_ref,
                "state": dict(snapshot.state),
            }
        ),
        authority=metadata.authority,
        evidence_cutoff=metadata.evidence_cutoff.astimezone(UTC),
        recorded_at=metadata.recorded_at.astimezone(UTC),
        freshness_ceiling_seconds=metadata.freshness_ceiling_seconds,
        evidence_refs=tuple(sorted(set(metadata.evidence_refs))),
    )


def _expires_at(lineage: EvidenceSourceLineage) -> datetime:
    return lineage.evidence_cutoff.astimezone(UTC) + timedelta(
        seconds=lineage.freshness_ceiling_seconds
    )


__all__ = [
    "EvidenceConflictCurrentReader",
    "EvidenceConflictCandidatePublisher",
    "EvidenceConflictDisposition",
    "EvidenceConflictRevision",
    "EvidenceConflictSink",
    "EvidenceConflictStatus",
    "EvidenceSourceLineage",
    "build_cross_source_evidence_conflict",
    "current_evidence_conflict_ceiling",
    "evidence_conflict_ceiling",
    "evidence_conflict_slot_ref",
]
