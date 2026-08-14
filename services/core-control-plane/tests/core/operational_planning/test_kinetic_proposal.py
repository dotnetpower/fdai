"""Adversarial contract tests for argument-bound kinetic proposals."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fdai.core.ontology_platform.functions import ontology_function_digest
from fdai.core.ontology_platform.kinetics import ActionArgumentBinding, MutationPlan
from fdai.core.ontology_platform.planning import build_mutation_plan
from fdai.core.operational_planning import KineticActionProposal
from fdai.shared.contracts.models import ActionLockScope
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from pydantic import ValidationError
from tests.core.ontology_platform.test_reconciliation import _fixture


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _plan(arguments: dict[str, object] | None = None) -> MutationPlan:
    _release, _target, base, _action_type = _fixture()
    values = arguments or {}
    bindings = tuple(
        ActionArgumentBinding(
            name=name,
            value_digest=ontology_function_digest(value),
            redacted=False,
            safe_value_json=_canonical(value),
        )
        for name, value in sorted(values.items())
    )
    return build_mutation_plan(
        action_type_ref=base.action_type_ref,
        planner_ref=base.planner_ref,
        targets=tuple(
            OntologyObjectRecord(
                id=target.object_id,
                object_type=target.type_ref.name,
                properties={},
                revision=target.revision,
                type_ref=target.type_ref,
            )
            for target in base.targets
        ),
        effects=base.effects,
        rollback_effects=base.rollback_effects,
        expected_effects=base.expected_effects,
        created_at=base.created_at,
        max_affected_objects=base.max_affected_objects or 1,
        schema_version="2.0.0",
        arguments_digest=ontology_function_digest(values),
        argument_bindings=bindings,
        read_set_receipt_digests=base.read_set_receipt_digests,
        criterion_receipt_digests=base.criterion_receipt_digests,
        transaction_mode=base.transaction_mode,
        lock_scope=base.lock_scope,
        lock_keys=base.lock_keys,
        irreversible=base.irreversible,
    )


def _proposal(arguments: dict[str, object] | None = None) -> KineticActionProposal:
    values = arguments or {}
    plan = _plan(values)
    return KineticActionProposal.create(
        correlation_id="correlation-1",
        process_id="process-1",
        operational_plan_id=plan.planner_ref,
        selected_option_id="option-1",
        plan=plan,
        target_resource_ref=plan.targets[0].object_id,
        arguments=values,
        created_at=plan.created_at + timedelta(seconds=1),
    )


def _rebuild(
    plan: MutationPlan,
    *,
    targets: tuple[OntologyObjectRecord, ...] | None = None,
    argument_bindings: tuple[ActionArgumentBinding, ...] | None = None,
    lock_scope: ActionLockScope | None = None,
    lock_keys: tuple[str, ...] | None = None,
    max_affected_objects: int | None = None,
) -> MutationPlan:
    target_records = targets or tuple(
        OntologyObjectRecord(
            id=target.object_id,
            object_type=target.type_ref.name,
            properties={},
            revision=target.revision,
            type_ref=target.type_ref,
        )
        for target in plan.targets
    )
    return build_mutation_plan(
        action_type_ref=plan.action_type_ref,
        planner_ref=plan.planner_ref,
        targets=target_records,
        effects=plan.effects,
        rollback_effects=plan.rollback_effects,
        expected_effects=plan.expected_effects,
        created_at=plan.created_at,
        max_affected_objects=max_affected_objects or plan.max_affected_objects or 1,
        schema_version=plan.schema_version,
        arguments_digest=plan.arguments_digest,
        argument_bindings=(
            argument_bindings if argument_bindings is not None else plan.argument_bindings
        ),
        read_set_receipt_digests=plan.read_set_receipt_digests,
        criterion_receipt_digests=plan.criterion_receipt_digests,
        transaction_mode=plan.transaction_mode,
        lock_scope=lock_scope or plan.lock_scope,
        lock_keys=lock_keys or plan.lock_keys,
        irreversible=plan.irreversible,
    )


def test_proposal_is_content_addressed_and_replay_stable() -> None:
    first = _proposal({"reason": "Scale for verified demand.", "replica_count": 3})
    replay = _proposal({"replica_count": 3, "reason": "Scale for verified demand."})

    assert replay == first
    assert replay.arguments() == {
        "reason": "Scale for verified demand.",
        "replica_count": 3,
    }
    assert KineticActionProposal.model_validate_json(first.model_dump_json()) == first


def test_proposal_identity_rejects_content_substitution() -> None:
    proposal = _proposal()
    raw = proposal.model_dump(mode="json")
    raw["correlation_id"] = "correlation-substituted"

    with pytest.raises(ValidationError, match="id does not match"):
        KineticActionProposal.model_validate(raw)


def test_plan_identity_rejects_content_substitution() -> None:
    plan = _plan()
    target = plan.targets[0].model_copy(update={"revision": 2})
    tampered = plan.model_copy(update={"targets": (target,)})

    with pytest.raises(ValidationError, match="plan identity does not match"):
        KineticActionProposal.create(
            correlation_id="correlation-1",
            process_id="process-1",
            operational_plan_id=tampered.planner_ref,
            selected_option_id="option-1",
            plan=tampered,
            target_resource_ref=target.object_id,
            arguments={},
            created_at=tampered.created_at,
        )


def test_v1_plan_is_rejected_without_upgrade() -> None:
    plan = _plan().model_copy(update={"schema_version": "1.0.0"})

    with pytest.raises(ValidationError, match="existing semantic V2 plan"):
        KineticActionProposal.create(
            correlation_id="correlation-1",
            process_id="process-1",
            operational_plan_id=plan.planner_ref,
            selected_option_id="option-1",
            plan=plan,
            target_resource_ref=plan.targets[0].object_id,
            arguments={},
            created_at=plan.created_at,
        )


def test_operational_plan_lineage_must_match_planner() -> None:
    plan = _plan()

    with pytest.raises(ValidationError, match="does not cite"):
        KineticActionProposal.create(
            correlation_id="correlation-1",
            process_id="process-1",
            operational_plan_id="operational-plan:substituted",
            selected_option_id="option-1",
            plan=plan,
            target_resource_ref=plan.targets[0].object_id,
            arguments={},
            created_at=plan.created_at,
        )


def test_target_substitution_is_rejected() -> None:
    plan = _plan()

    with pytest.raises(ValidationError, match="target does not match"):
        KineticActionProposal.create(
            correlation_id="correlation-1",
            process_id="process-1",
            operational_plan_id=plan.planner_ref,
            selected_option_id="option-1",
            plan=plan,
            target_resource_ref="workload-substituted",
            arguments={},
            created_at=plan.created_at,
        )


def test_multi_target_plan_is_rejected() -> None:
    plan = _plan()
    target = plan.targets[0]
    first_record = OntologyObjectRecord(
        id=target.object_id,
        object_type=target.type_ref.name,
        properties={},
        revision=target.revision,
        type_ref=target.type_ref,
    )
    second_record = OntologyObjectRecord(
        id="workload-b",
        object_type=first_record.object_type,
        properties={},
        revision=first_record.revision,
        type_ref=first_record.type_ref,
    )
    unsafe = _rebuild(
        plan,
        targets=(first_record, second_record),
        lock_scope=ActionLockScope.TARGET_SET,
        lock_keys=("ontology-target:workload-a", "ontology-target:workload-b"),
        max_affected_objects=2,
    )

    with pytest.raises(ValidationError, match="exactly one target"):
        KineticActionProposal.create(
            correlation_id="correlation-1",
            process_id="process-1",
            operational_plan_id=unsafe.planner_ref,
            selected_option_id="option-1",
            plan=unsafe,
            target_resource_ref=target.object_id,
            arguments={},
            created_at=unsafe.created_at,
        )


def test_argument_body_must_match_plan_digest() -> None:
    plan = _plan({"replica_count": 3})

    with pytest.raises(ValidationError, match="arguments do not match"):
        KineticActionProposal.create(
            correlation_id="correlation-1",
            process_id="process-1",
            operational_plan_id=plan.planner_ref,
            selected_option_id="option-1",
            plan=plan,
            target_resource_ref=plan.targets[0].object_id,
            arguments={"replica_count": 4},
            created_at=plan.created_at,
        )


def test_argument_binding_set_must_be_complete() -> None:
    plan = _rebuild(_plan({"replica_count": 3}), argument_bindings=())

    with pytest.raises(ValidationError, match="bindings are incomplete"):
        KineticActionProposal.create(
            correlation_id="correlation-1",
            process_id="process-1",
            operational_plan_id=plan.planner_ref,
            selected_option_id="option-1",
            plan=plan,
            target_resource_ref=plan.targets[0].object_id,
            arguments={"replica_count": 3},
            created_at=plan.created_at,
        )


def test_argument_binding_value_digest_must_match() -> None:
    plan = _plan({"replica_count": 3})
    binding = plan.argument_bindings[0].model_copy(update={"value_digest": "sha256:" + "f" * 64})
    plan = _rebuild(plan, argument_bindings=(binding,))

    with pytest.raises(ValidationError, match="binding digest"):
        KineticActionProposal.create(
            correlation_id="correlation-1",
            process_id="process-1",
            operational_plan_id=plan.planner_ref,
            selected_option_id="option-1",
            plan=plan,
            target_resource_ref=plan.targets[0].object_id,
            arguments={"replica_count": 3},
            created_at=plan.created_at,
        )


def test_safe_argument_projection_must_match() -> None:
    plan = _plan({"replica_count": 3})
    binding = plan.argument_bindings[0].model_copy(update={"safe_value_json": "4"})
    plan = _rebuild(plan, argument_bindings=(binding,))

    with pytest.raises(ValidationError, match="safe argument projection"):
        KineticActionProposal.create(
            correlation_id="correlation-1",
            process_id="process-1",
            operational_plan_id=plan.planner_ref,
            selected_option_id="option-1",
            plan=plan,
            target_resource_ref=plan.targets[0].object_id,
            arguments={"replica_count": 3},
            created_at=plan.created_at,
        )


def test_noncanonical_argument_json_is_rejected() -> None:
    proposal = _proposal({"a": 1, "b": 2})
    raw = proposal.model_dump(mode="json")
    raw["arguments_json"] = '{"b":2,"a":1}'

    with pytest.raises(ValidationError, match="canonical JSON object"):
        KineticActionProposal.model_validate(raw)


def test_proposal_cannot_predate_plan() -> None:
    plan = _plan()

    with pytest.raises(ValidationError, match="cannot predate"):
        KineticActionProposal.create(
            correlation_id="correlation-1",
            process_id="process-1",
            operational_plan_id=plan.planner_ref,
            selected_option_id="option-1",
            plan=plan,
            target_resource_ref=plan.targets[0].object_id,
            arguments={},
            created_at=plan.created_at - timedelta(microseconds=1),
        )


def test_proposal_rejects_naive_timestamp() -> None:
    plan = _plan()

    with pytest.raises(ValidationError, match="timezone-aware"):
        KineticActionProposal.create(
            correlation_id="correlation-1",
            process_id="process-1",
            operational_plan_id=plan.planner_ref,
            selected_option_id="option-1",
            plan=plan,
            target_resource_ref=plan.targets[0].object_id,
            arguments={},
            created_at=plan.created_at.replace(tzinfo=None),
        )


def test_proposal_rejects_oversized_arguments() -> None:
    plan = _plan({"reason": "x" * 1_048_576})

    with pytest.raises(ValidationError, match="1048576"):
        KineticActionProposal.create(
            correlation_id="correlation-1",
            process_id="process-1",
            operational_plan_id=plan.planner_ref,
            selected_option_id="option-1",
            plan=plan,
            target_resource_ref=plan.targets[0].object_id,
            arguments={"reason": "x" * 1_048_576},
            created_at=plan.created_at,
        )


def test_unknown_contract_field_is_rejected() -> None:
    raw = _proposal().model_dump(mode="json")
    raw["mode"] = "enforce"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        KineticActionProposal.model_validate(raw)
