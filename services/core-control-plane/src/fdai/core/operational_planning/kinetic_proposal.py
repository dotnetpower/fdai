"""Authority-free handoff contract for an existing exact kinetic plan."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Annotated, Any, Self

from pydantic import Field, model_validator

from fdai.core.ontology_platform.functions import ontology_function_digest
from fdai.core.ontology_platform.kinetics import MutationPlan
from fdai.core.ontology_platform.planning import build_mutation_plan
from fdai.shared.contracts.models import ContractBase, OntologyDeclarationKind, SemVer
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

_MAX_PROPOSAL_BYTES = 1_048_576
_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_PROPOSAL_PATTERN = r"^kinetic-action-proposal:[a-f0-9]{64}$"


class KineticActionProposal(ContractBase):
    """Bind one existing V2 plan to exact Action arguments and planning lineage.

    The contract is proposal evidence only. It carries no mode, approval, promotion,
    or execution authority, and it cannot upgrade a legacy Action into a semantic plan.
    """

    schema_version: SemVer = "1.0.0"
    proposal_id: Annotated[str, Field(pattern=_PROPOSAL_PATTERN)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    process_id: Annotated[str, Field(min_length=1, max_length=200)]
    operational_plan_id: Annotated[str, Field(min_length=1, max_length=512)]
    selected_option_id: Annotated[str, Field(min_length=1, max_length=256)]
    plan: MutationPlan
    target_resource_ref: Annotated[str, Field(min_length=1, max_length=512)]
    arguments_json: Annotated[str, Field(min_length=2, max_length=_MAX_PROPOSAL_BYTES)]
    arguments_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        correlation_id: str,
        process_id: str,
        operational_plan_id: str,
        selected_option_id: str,
        plan: MutationPlan,
        target_resource_ref: str,
        arguments: Mapping[str, Any],
        created_at: datetime,
    ) -> Self:
        """Canonicalize exact inputs and create their content-addressed proposal."""

        normalized_plan = MutationPlan.model_validate_json(plan.model_dump_json())
        arguments_json = _canonical_json(dict(arguments))
        arguments_digest = ontology_function_digest(json.loads(arguments_json))
        prototype = cls.model_construct(
            proposal_id="kinetic-action-proposal:" + "0" * 64,
            schema_version="1.0.0",
            correlation_id=correlation_id,
            process_id=process_id,
            operational_plan_id=operational_plan_id,
            selected_option_id=selected_option_id,
            plan=normalized_plan,
            target_resource_ref=target_resource_ref,
            arguments_json=arguments_json,
            arguments_digest=arguments_digest,
            created_at=created_at,
        )
        digest = ontology_function_digest(
            prototype.model_dump(mode="json", exclude={"proposal_id"})
        )
        return cls(
            proposal_id=f"kinetic-action-proposal:{digest.removeprefix('sha256:')}",
            schema_version="1.0.0",
            correlation_id=correlation_id,
            process_id=process_id,
            operational_plan_id=operational_plan_id,
            selected_option_id=selected_option_id,
            plan=normalized_plan,
            target_resource_ref=target_resource_ref,
            arguments_json=arguments_json,
            arguments_digest=arguments_digest,
            created_at=created_at,
        )

    @model_validator(mode="after")
    def _binding_is_exact_and_bounded(self) -> KineticActionProposal:
        if self.plan.schema_version != "2.0.0":
            raise ValueError("kinetic action proposal requires an existing semantic V2 plan")
        if self.plan.action_type_ref.kind is not OntologyDeclarationKind.ACTION:
            raise ValueError("kinetic action proposal plan MUST reference an ActionType")
        _validate_plan_identity(self.plan)
        if self.plan.planner_ref != self.operational_plan_id:
            raise ValueError("kinetic action proposal plan does not cite its operational plan")
        if len(self.plan.targets) != 1:
            raise ValueError("kinetic action proposal requires exactly one target")
        if self.plan.targets[0].object_id != self.target_resource_ref:
            raise ValueError("kinetic action proposal target does not match its plan")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("kinetic action proposal created_at MUST be timezone-aware")
        if self.created_at.utcoffset() != timedelta(0):
            raise ValueError("kinetic action proposal created_at MUST use UTC")
        if self.created_at < self.plan.created_at:
            raise ValueError("kinetic action proposal cannot predate its plan")

        arguments = _arguments(self.arguments_json)
        expected_digest = ontology_function_digest(arguments)
        if (
            self.arguments_digest != expected_digest
            or self.plan.arguments_digest != expected_digest
        ):
            raise ValueError("kinetic action proposal arguments do not match its plan")
        bindings = {binding.name: binding for binding in self.plan.argument_bindings}
        if tuple(sorted(bindings)) != tuple(sorted(arguments)):
            raise ValueError("kinetic action proposal argument bindings are incomplete")
        for name, value in arguments.items():
            binding = bindings[name]
            if binding.value_digest != ontology_function_digest(value):
                raise ValueError("kinetic action proposal argument binding digest does not match")
            safe_json = _canonical_json("<redacted>" if binding.redacted else value)
            if binding.safe_value_json != safe_json:
                raise ValueError("kinetic action proposal safe argument projection does not match")

        material = self.model_dump(mode="json", exclude={"proposal_id"})
        expected_id = ontology_function_digest(material)
        if self.proposal_id != (f"kinetic-action-proposal:{expected_id.removeprefix('sha256:')}"):
            raise ValueError("kinetic action proposal id does not match its content")
        if len(_canonical_json(material).encode("utf-8")) > _MAX_PROPOSAL_BYTES:
            raise ValueError("kinetic action proposal exceeds the canonical byte limit")
        return self

    def arguments(self) -> dict[str, Any]:
        """Return a fresh exact argument mapping for typed ingress validation."""

        return _arguments(self.arguments_json)


def _arguments(arguments_json: str) -> dict[str, Any]:
    try:
        decoded = json.loads(arguments_json)
    except json.JSONDecodeError as exc:
        raise ValueError("kinetic action proposal arguments MUST be canonical JSON") from exc
    if not isinstance(decoded, dict) or _canonical_json(decoded) != arguments_json:
        raise ValueError("kinetic action proposal arguments MUST be one canonical JSON object")
    return decoded


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("kinetic action proposal values MUST be canonical JSON") from exc


def _validate_plan_identity(plan: MutationPlan) -> None:
    targets = tuple(
        OntologyObjectRecord(
            id=target.object_id,
            object_type=target.type_ref.name,
            properties={},
            revision=target.revision,
            type_ref=target.type_ref,
        )
        for target in plan.targets
    )
    rebuilt = build_mutation_plan(
        action_type_ref=plan.action_type_ref,
        planner_ref=plan.planner_ref,
        targets=targets,
        effects=plan.effects,
        rollback_effects=plan.rollback_effects,
        expected_effects=plan.expected_effects,
        created_at=plan.created_at,
        max_affected_objects=plan.max_affected_objects or len(targets),
        schema_version=plan.schema_version,
        arguments_digest=plan.arguments_digest,
        argument_bindings=plan.argument_bindings,
        read_set_receipt_digests=plan.read_set_receipt_digests,
        criterion_receipt_digests=plan.criterion_receipt_digests,
        transaction_mode=plan.transaction_mode,
        lock_scope=plan.lock_scope,
        lock_keys=plan.lock_keys,
        irreversible=plan.irreversible,
    )
    if rebuilt.plan_id != plan.plan_id or rebuilt.digest != plan.digest:
        raise ValueError("kinetic action proposal plan identity does not match its content")


__all__ = ["KineticActionProposal"]
