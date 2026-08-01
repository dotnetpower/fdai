"""Kinetic ontology contracts that remain proposal and evidence only."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, model_validator

from fdai.shared.contracts.models import ContractBase, OntologyTypeRef, SemVer


class MutationEffectKind(StrEnum):
    EXPECTED_PROPERTY = "expected_property"
    INTERNAL_WRITE = "internal_write"
    CATALOG_PR = "catalog_pr"
    PROVIDER_COMMAND = "provider_command"
    NOTIFICATION = "notification"
    SCHEDULE = "schedule"


class TargetRevision(ContractBase):
    object_id: Annotated[str, Field(min_length=1)]
    type_ref: OntologyTypeRef
    revision: int = Field(ge=1)


class MutationEffect(ContractBase):
    kind: MutationEffectKind
    target_id: Annotated[str, Field(min_length=1)]
    property_name: str | None = None
    value: Any = None
    command_ref: str | None = None


class MutationPlan(ContractBase):
    schema_version: SemVer = "1.0.0"
    plan_id: Annotated[str, Field(pattern=r"^mutation-plan:[a-f0-9]{64}$")]
    digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    action_type_ref: OntologyTypeRef
    planner_ref: Annotated[str, Field(min_length=1)]
    targets: tuple[TargetRevision, ...]
    effects: tuple[MutationEffect, ...]
    rollback_effects: tuple[MutationEffect, ...]
    expected_effects: tuple[MutationEffect, ...] = ()
    created_at: datetime

    @model_validator(mode="after")
    def _has_bounded_targets_and_recovery(self) -> MutationPlan:
        if not self.targets:
            raise ValueError("MutationPlan requires at least one target")
        if not self.effects:
            raise ValueError("MutationPlan requires at least one effect")
        if not self.rollback_effects:
            raise ValueError("MutationPlan requires rollback or compensation effects")
        effect_targets = {item.target_id for item in self.effects}
        rollback_targets = {item.target_id for item in self.rollback_effects}
        if not effect_targets <= rollback_targets:
            raise ValueError("rollback effects MUST cover every mutation target")
        if self.created_at.tzinfo is None:
            raise ValueError("MutationPlan.created_at MUST be timezone-aware")
        return self


class OntologyFunctionKind(StrEnum):
    QUERY = "query"
    DERIVE = "derive"
    VALIDATE = "validate"
    PLAN = "plan"


class OntologyFunctionType(ContractBase):
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")]
    version: SemVer
    kind: OntologyFunctionKind
    artifact_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    publisher: Annotated[str, Field(min_length=1)]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    read_sets: tuple[str, ...] = ()
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    memory_bytes: int = Field(default=134_217_728, ge=1, le=1_073_741_824)
    network_allowed: bool = False


class CriterionResult(ContractBase):
    passed: bool
    reason_code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    evidence_refs: tuple[str, ...]


class AuthorityClass(StrEnum):
    CATALOG_OWNED = "catalog_owned"
    FDAI_OWNED = "fdai_owned"
    PROVIDER_OBSERVED = "provider_observed"
    LEDGER_OWNED = "ledger_owned"
    DERIVED = "derived"


class ProjectionBinding(ContractBase):
    binding_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")]
    source_id: Annotated[str, Field(min_length=1)]
    object_type_ref: OntologyTypeRef
    authority_class: AuthorityClass
    identity_field: Annotated[str, Field(min_length=1)]
    property_map: dict[str, str]
    watermark_field: Annotated[str, Field(min_length=1)]
    delete_field: str | None = None
    max_batch_size: int = Field(default=1000, ge=1, le=10_000)


class ReconciliationStatus(StrEnum):
    MATCHED = "matched"
    MISMATCHED = "mismatched"
    TIMED_OUT = "timed_out"
    UNSCORABLE = "unscorable"


class ReconciliationReceipt(ContractBase):
    plan_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    status: ReconciliationStatus
    observed_at: datetime
    evidence_refs: Annotated[tuple[str, ...], Field(min_length=1)]
    mismatches: tuple[str, ...] = ()


class ProjectedBatch(ContractBase):
    objects: tuple[Any, ...]
    deleted_ids: tuple[str, ...]
    watermark: str | None


__all__ = [
    "AuthorityClass",
    "CriterionResult",
    "MutationEffect",
    "MutationEffectKind",
    "MutationPlan",
    "OntologyFunctionKind",
    "OntologyFunctionType",
    "ProjectionBinding",
    "ProjectedBatch",
    "ReconciliationReceipt",
    "ReconciliationStatus",
    "TargetRevision",
]
