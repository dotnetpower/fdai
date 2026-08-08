"""Kinetic ontology contracts that remain proposal and evidence only."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import Field, model_validator

from fdai.shared.contracts.models import (
    ActionLockScope,
    ActionTransactionMode,
    ContractBase,
    OntologyDeclarationRef,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyTypeRef,
    SemVer,
)


class MutationEffectKind(StrEnum):
    EXPECTED_PROPERTY = "expected_property"
    EXPECTED_OBSERVATION = "expected_observation"
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
    effect_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")] | None = None
    kind: MutationEffectKind
    target_id: Annotated[str, Field(min_length=1)]
    property_name: str | None = None
    value: Any = None
    command_ref: str | None = None
    observation_ref: str | None = None
    function_ref: OntologyDeclarationRef | None = None

    @model_validator(mode="after")
    def _effect_shape_is_explicit(self) -> MutationEffect:
        if self.kind is MutationEffectKind.PROVIDER_COMMAND and not self.command_ref:
            raise ValueError("provider_command MutationEffect requires command_ref")
        if self.kind is MutationEffectKind.EXPECTED_PROPERTY and not self.property_name:
            raise ValueError("expected_property MutationEffect requires property_name")
        return self


class ActionArgumentBinding(ContractBase):
    """Digest-bound audit projection of one canonical action argument."""

    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    value_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    redacted: bool
    safe_value_json: str


class ActionReadSetReceipt(ContractBase):
    """Content-addressed completeness and freshness proof for one declared read set."""

    function_ref: OntologyDeclarationRef
    properties: tuple[Annotated[str, Field(min_length=1, max_length=256)], ...]
    object_count: int = Field(ge=0)
    complete: bool
    truncated: bool
    observed_at: datetime
    fresh_until: datetime
    evidence_refs: Annotated[tuple[str, ...], Field(min_length=1)]
    receipt_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]

    @classmethod
    def create(cls, **values: Any) -> Self:
        """Build a receipt whose digest covers every supplied evidence field."""

        values = dict(values)
        values["function_ref"] = OntologyDeclarationRef.model_validate(values["function_ref"])
        values["properties"] = tuple(values["properties"])
        values["evidence_refs"] = tuple(values["evidence_refs"])
        prototype = cls.model_construct(
            **values,
            receipt_digest="sha256:" + "0" * 64,
        )
        material = prototype.model_dump(mode="json", exclude={"receipt_digest"})
        return cls(**values, receipt_digest=_content_digest(material))

    @model_validator(mode="after")
    def _receipt_is_content_addressed(self) -> ActionReadSetReceipt:
        _require_receipt_times(self.observed_at, self.fresh_until)
        if self.receipt_digest != _content_digest(
            self.model_dump(mode="json", exclude={"receipt_digest"})
        ):
            raise ValueError("read-set receipt digest does not match its content")
        return self


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
    arguments_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")] | None = None
    argument_bindings: tuple[ActionArgumentBinding, ...] = ()
    read_set_receipt_digests: tuple[
        Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")], ...
    ] = ()
    criterion_receipt_digests: tuple[
        Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")], ...
    ] = ()
    transaction_mode: ActionTransactionMode | None = None
    lock_scope: ActionLockScope | None = None
    lock_keys: tuple[Annotated[str, Field(min_length=1)], ...] = ()
    max_affected_objects: int | None = Field(default=None, ge=1, le=1000)
    irreversible: bool = False

    @model_validator(mode="after")
    def _has_bounded_targets_and_recovery(self) -> MutationPlan:
        if not self.targets:
            raise ValueError("MutationPlan requires at least one target")
        if not self.effects:
            raise ValueError("MutationPlan requires at least one effect")
        if not self.rollback_effects and not self.irreversible:
            raise ValueError("MutationPlan requires rollback or compensation effects")
        effect_keys = {(item.effect_id, item.target_id) for item in self.effects}
        rollback_keys = {(item.effect_id, item.target_id) for item in self.rollback_effects}
        if not self.irreversible and not effect_keys <= rollback_keys:
            raise ValueError("rollback effects MUST cover every mutation target")
        if self.created_at.tzinfo is None:
            raise ValueError("MutationPlan.created_at MUST be timezone-aware")
        if self.schema_version == "2.0.0":
            if self.arguments_digest is None:
                raise ValueError("semantic MutationPlan requires arguments_digest")
            if self.transaction_mode is None or self.lock_scope is None:
                raise ValueError("semantic MutationPlan requires transaction and lock policy")
            if self.max_affected_objects is None or not self.lock_keys:
                raise ValueError("semantic MutationPlan requires bounded deterministic lock keys")
            if tuple(sorted(set(self.lock_keys))) != self.lock_keys:
                raise ValueError("semantic MutationPlan lock_keys MUST be sorted and unique")
            expected_lock_keys = tuple(
                sorted(f"ontology-target:{target.object_id}" for target in self.targets)
            )
            if self.lock_keys != expected_lock_keys:
                raise ValueError("semantic MutationPlan lock_keys MUST match exact targets")
            if len(self.targets) > self.max_affected_objects:
                raise ValueError("semantic MutationPlan targets exceed max_affected_objects")
            if self.lock_scope is ActionLockScope.TARGET and len(self.targets) != 1:
                raise ValueError("target lock scope requires exactly one mutation target")
            argument_names = tuple(item.name for item in self.argument_bindings)
            if tuple(sorted(set(argument_names))) != argument_names:
                raise ValueError(
                    "semantic MutationPlan argument bindings MUST be sorted and unique"
                )
            if len(set(self.read_set_receipt_digests)) != len(self.read_set_receipt_digests):
                raise ValueError("semantic MutationPlan read-set receipt digests MUST be unique")
            if len(set(self.criterion_receipt_digests)) != len(self.criterion_receipt_digests):
                raise ValueError("semantic MutationPlan criterion receipt digests MUST be unique")
        return self


class CriterionResult(ContractBase):
    criterion_ref: str | None = None
    function_ref: OntologyDeclarationRef | None = None
    passed: bool
    reason_code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    evidence_refs: Annotated[tuple[str, ...], Field(min_length=1)]
    complete: bool
    truncated: bool
    observed_at: datetime
    fresh_until: datetime
    receipt_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]

    @classmethod
    def create(cls, **values: Any) -> Self:
        """Build a criterion receipt whose digest covers its result and evidence."""

        values = dict(values)
        if values.get("function_ref") is not None:
            values["function_ref"] = OntologyDeclarationRef.model_validate(values["function_ref"])
        values["evidence_refs"] = tuple(values["evidence_refs"])
        prototype = cls.model_construct(
            **values,
            receipt_digest="sha256:" + "0" * 64,
        )
        material = prototype.model_dump(mode="json", exclude={"receipt_digest"})
        return cls(**values, receipt_digest=_content_digest(material))

    @model_validator(mode="after")
    def _criterion_receipt_is_canonical(self) -> CriterionResult:
        if (self.criterion_ref is None) == (self.function_ref is None):
            raise ValueError("CriterionResult requires exactly one criterion reference")
        _require_receipt_times(self.observed_at, self.fresh_until)
        if self.receipt_digest != _content_digest(
            self.model_dump(mode="json", exclude={"receipt_digest"})
        ):
            raise ValueError("criterion receipt digest does not match its content")
        return self


def _content_digest(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=_json_default,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("action receipt values MUST be canonical JSON") from exc
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError(f"unsupported action receipt value {type(value).__name__}")


def _require_receipt_times(observed_at: datetime, fresh_until: datetime) -> None:
    if observed_at.tzinfo is None or fresh_until.tzinfo is None:
        raise ValueError("action receipt times MUST be timezone-aware")
    if fresh_until < observed_at:
        raise ValueError("action receipt fresh_until precedes observed_at")


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
    "ActionArgumentBinding",
    "ActionReadSetReceipt",
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
