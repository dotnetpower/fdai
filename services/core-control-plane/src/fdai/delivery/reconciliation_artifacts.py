"""Durable exact-plan artifacts for ordinary effect reconciliation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import Field, model_validator

from fdai.core.ontology_platform.action_plans import validate_action_plan_semantics
from fdai.core.ontology_platform.functions import ontology_function_digest
from fdai.core.ontology_platform.kinetics import MutationPlan
from fdai.core.ontology_platform.reconciliation_binding import ResolvedReconciliationArtifacts
from fdai.core.ontology_platform.reconciliation_contracts import reconciliation_content_digest
from fdai.shared.contracts.models import (
    Action,
    ContractBase,
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyRelease,
    OntologyReleaseRef,
    OntologyTypeRef,
    Operation,
    SemVer,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.state_store import StateStore

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_RECEIPT_PATTERN = r"^kinetic-safety:[a-f0-9]{64}$"


class KineticSafetyReceipt(ContractBase):
    """Immutable delivery evidence binding an Action to an existing exact V2 plan."""

    schema_version: SemVer = "1.0.0"
    receipt_id: Annotated[str, Field(pattern=_RECEIPT_PATTERN)]
    action_id: UUID
    event_id: UUID
    action_idempotency_key: Annotated[str, Field(min_length=1, max_length=512)]
    action_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    ontology_release_ref: OntologyReleaseRef
    action_type_ref: OntologyTypeRef
    plan_id: Annotated[str, Field(pattern=r"^mutation-plan:[a-f0-9]{64}$")]
    plan_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    target_resource_ref: Annotated[str, Field(min_length=1, max_length=512)]
    target_revision: int = Field(ge=1)
    operation: Operation
    arguments_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    safeguards_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    created_at: datetime
    receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @classmethod
    def seal(
        cls,
        *,
        action: Action,
        plan: MutationPlan,
        action_type: OntologyActionType,
        active_release: OntologyRelease,
    ) -> Self:
        """Validate all exact bodies and seal their no-authority binding."""

        _validate_artifacts(
            action=action,
            plan=plan,
            action_type=action_type,
            active_release=active_release,
        )
        target = plan.targets[0]
        action_digest = reconciliation_content_digest(action.model_dump(mode="json"))
        ontology_release_ref = active_release.ref()
        arguments_digest = plan.arguments_digest
        if arguments_digest is None:  # pragma: no cover - V2 plan model invariant
            raise RuntimeError("semantic V2 plan lost its arguments digest")
        safeguards_digest = reconciliation_content_digest(
            {
                "stop_conditions": [
                    condition.model_dump(mode="json") for condition in action.stop_conditions
                ],
                "rollback_ref": action.rollback_ref.model_dump(mode="json"),
                "blast_radius": action.blast_radius.model_dump(mode="json"),
                "mode": action.mode.value,
                "transaction_mode": plan.transaction_mode,
                "lock_scope": plan.lock_scope,
                "lock_keys": plan.lock_keys,
                "max_affected_objects": plan.max_affected_objects,
                "irreversible": plan.irreversible,
            }
        )
        created_at = action.created_at.astimezone(UTC)
        prototype = cls.model_construct(
            receipt_id="kinetic-safety:" + "0" * 64,
            action_id=action.action_id,
            event_id=action.event_id,
            action_idempotency_key=action.idempotency_key,
            action_digest=action_digest,
            ontology_release_ref=ontology_release_ref,
            action_type_ref=plan.action_type_ref,
            plan_id=plan.plan_id,
            plan_digest=plan.digest,
            target_resource_ref=target.object_id,
            target_revision=target.revision,
            operation=action.operation,
            arguments_digest=arguments_digest,
            safeguards_digest=safeguards_digest,
            created_at=created_at,
            receipt_digest="sha256:" + "0" * 64,
        )
        digest = reconciliation_content_digest(
            prototype.model_dump(mode="json", exclude={"receipt_id", "receipt_digest"})
        )
        return cls(
            receipt_id=f"kinetic-safety:{digest.removeprefix('sha256:')}",
            action_id=action.action_id,
            event_id=action.event_id,
            action_idempotency_key=action.idempotency_key,
            action_digest=action_digest,
            ontology_release_ref=ontology_release_ref,
            action_type_ref=plan.action_type_ref,
            plan_id=plan.plan_id,
            plan_digest=plan.digest,
            target_resource_ref=target.object_id,
            target_revision=target.revision,
            operation=action.operation,
            arguments_digest=arguments_digest,
            safeguards_digest=safeguards_digest,
            created_at=created_at,
            receipt_digest=digest,
        )

    def bind(
        self,
        *,
        action: Action,
        plan: MutationPlan,
        action_type: OntologyActionType,
        active_release: OntologyRelease,
    ) -> None:
        """Reject substituted artifact bodies for this receipt."""

        expected = type(self).seal(
            action=action,
            plan=plan,
            action_type=action_type,
            active_release=active_release,
        )
        if expected != self:
            raise ValueError("kinetic safety receipt does not match exact artifacts")

    @model_validator(mode="after")
    def _identity_is_canonical(self) -> KineticSafetyReceipt:
        if self.action_type_ref.kind is not OntologyDeclarationKind.ACTION:
            raise ValueError("kinetic safety receipt ActionType ref kind MUST be action")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("kinetic safety receipt created_at MUST be timezone-aware")
        values = self.model_dump(mode="json", exclude={"receipt_id", "receipt_digest"})
        expected = reconciliation_content_digest(values)
        if self.receipt_digest != expected:
            raise ValueError("kinetic safety receipt digest does not match content")
        if self.receipt_id != f"kinetic-safety:{expected.removeprefix('sha256:')}":
            raise ValueError("kinetic safety receipt id does not match content")
        return self


class KineticSafetyArtifactConflictError(RuntimeError):
    """The same Action identity was reused with different kinetic artifacts."""


class StateStoreExecutedActionArtifactStore:
    """Atomically persist and resolve exact pre-dispatch kinetic artifacts."""

    _KEY_PREFIX = "ontology:kinetic-safety-artifact:"
    _MAX_RECORD_BYTES = 16 * 1024 * 1024

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def store(
        self,
        *,
        action: Action,
        plan: MutationPlan,
        action_type: OntologyActionType,
        active_release: OntologyRelease,
    ) -> KineticSafetyReceipt:
        """Persist one immutable all-before-dispatch artifact record."""

        receipt = KineticSafetyReceipt.seal(
            action=action,
            plan=plan,
            action_type=action_type,
            active_release=active_release,
        )
        record = _record(
            receipt=receipt,
            plan=plan,
            action_type=action_type,
            active_release=active_release,
        )
        if len(json.dumps(record, separators=(",", ":"), sort_keys=True).encode("utf-8")) > (
            self._MAX_RECORD_BYTES
        ):
            raise ValueError("kinetic safety artifact exceeds the canonical byte limit")
        key = self._key(action)
        created = await self._store.write_state_with_audit_if_absent(
            key,
            record,
            {
                "action_kind": "kinetic_safety.artifact_stored",
                "actor": "kinetic-safety-artifact-store",
                "action_id": str(action.action_id),
                "receipt_id": receipt.receipt_id,
                "receipt_digest": receipt.receipt_digest,
                "plan_digest": receipt.plan_digest,
            },
        )
        if created:
            return receipt
        existing = await self._store.read_state(key)
        if existing is None:
            raise RuntimeError("kinetic safety artifact write lost durable state")
        prior = _parse(existing)
        if prior[0] != receipt or dict(existing) != record:
            raise KineticSafetyArtifactConflictError(
                "kinetic safety Action identity was reused with different content"
            )
        return prior[0]

    async def resolve(self, action: Action) -> ResolvedReconciliationArtifacts | None:
        """Resolve only a previously stored exact V2 plan for this Action."""

        raw = await self._store.read_state(self._key(action))
        if raw is None:
            return None
        receipt, plan, action_type, active_release = _parse(raw)
        if receipt.action_digest != reconciliation_content_digest(action.model_dump(mode="json")):
            raise KineticSafetyArtifactConflictError(
                "kinetic safety stored Action does not match requested Action"
            )
        receipt.bind(
            action=action,
            plan=plan,
            action_type=action_type,
            active_release=active_release,
        )
        return ResolvedReconciliationArtifacts(
            plan=plan,
            action_type=action_type,
            active_release=active_release,
        )

    @classmethod
    def _key(cls, action: Action) -> str:
        return f"{cls._KEY_PREFIX}{action.action_id}"


def _record(
    *,
    receipt: KineticSafetyReceipt,
    plan: MutationPlan,
    action_type: OntologyActionType,
    active_release: OntologyRelease,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "action_id": str(receipt.action_id),
        "receipt": receipt.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json"),
        "action_type": action_type.model_dump(mode="json"),
        "ontology_release": active_release.model_dump(mode="json"),
    }


def _parse(
    raw: Mapping[str, Any],
) -> tuple[
    KineticSafetyReceipt,
    MutationPlan,
    OntologyActionType,
    OntologyRelease,
]:
    try:
        if raw.get("schema_version") != "1.0.0":
            raise ValueError("unsupported schema version")
        receipt = KineticSafetyReceipt.model_validate(raw["receipt"])
        plan = MutationPlan.model_validate(raw["plan"])
        action_type = OntologyActionType.model_validate(raw["action_type"])
        active_release = OntologyRelease.model_validate(raw["ontology_release"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("durable kinetic safety artifact failed validation") from exc
    if raw.get("action_id") != str(receipt.action_id):
        raise RuntimeError("durable kinetic safety artifact Action identity does not match")
    return receipt, plan, action_type, active_release


def _validate_artifacts(
    *,
    action: Action,
    plan: MutationPlan,
    action_type: OntologyActionType,
    active_release: OntologyRelease,
) -> None:
    if plan.schema_version != "2.0.0":
        raise ValueError("kinetic safety receipt requires an existing semantic V2 plan")
    if action.action_type_ref is None:
        raise ValueError("kinetic safety receipt requires an exact ActionType ref")
    validate_action_plan_semantics(
        action_type=action_type,
        release=active_release,
        plan=plan,
    )
    release_ref = active_release.type_ref(OntologyDeclarationKind.ACTION, action_type.name)
    declaration = next(
        item
        for item in active_release.declarations
        if item.kind is OntologyDeclarationKind.ACTION and item.name == action_type.name
    )
    action_declaration = build_ontology_release(action_types=(action_type,)).declarations[0]
    if action_declaration.declaration_digest != declaration.declaration_digest:
        raise ValueError("kinetic safety ActionType body does not match active release")
    if (
        action.action_type_ref != release_ref
        or plan.action_type_ref != release_ref
        or action.action_type != action_type.name
        or action.operation != action_type.operation
        or len(plan.targets) != 1
        or plan.targets[0].object_id != action.target_resource_ref
        or plan.arguments_digest != ontology_function_digest(action.params)
    ):
        raise ValueError("kinetic safety artifacts do not match the executed Action")
    if plan.created_at > action.created_at:
        raise ValueError("kinetic safety plan MUST exist before its Action")
    if action.blast_radius.count is not None and len(plan.targets) > action.blast_radius.count:
        raise ValueError("kinetic safety plan exceeds Action blast radius")


__all__ = [
    "KineticSafetyReceipt",
    "KineticSafetyArtifactConflictError",
    "StateStoreExecutedActionArtifactStore",
]
