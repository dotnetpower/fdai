"""ActionBuilder - safety-invariant mapping from Finding to Action."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fdai.core.executor.action_builder import (
    ActionBuilder,
    ActionBuildError,
)
from fdai.core.quality_gate import QualityCandidate
from fdai.core.tiers.t0_deterministic.models import Finding
from fdai.core.tiers.t1_lightweight import LearnedAction
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import (
    BlastRadiusScope,
    Category,
    CheckLogic,
    CheckLogicKind,
    Event,
    Mode,
    Operation,
    Provenance,
    Redistribution,
    Remediation,
    RollbackKind,
    Rule,
    RuleSource,
    Severity,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.readiness_remediation import ReadinessRemediationRequest

REPO_ROOT = Path(__file__).resolve().parents[5]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"


def _shipped_action_types() -> dict[str, object]:
    catalog = load_action_type_catalog(
        ACTION_TYPES_ROOT, schema_registry=PackageResourceSchemaRegistry()
    )
    return {a.name: a for a in catalog}


def _event() -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "e1",
            "source": "src",
            "event_type": "change_detected",
            "detected_at": "2026-07-05T08:00:00Z",
            "ingested_at": "2026-07-05T08:00:01Z",
            "mode": "shadow",
        }
    )


def _rule(rule_id: str, remediates: str, parameters: dict | None = None) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.HIGH,
        category=Category.SECURITY,
        resource_type="object-storage",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/x.rego"),
        remediation=Remediation(template_ref="remediation/x.tftpl"),
        remediates=remediates,
        parameters=parameters or {},
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def _finding(rule: Rule, *, resource_id: str = "rid-1") -> Finding:
    return Finding(
        finding_id=f"{rule.id}::{rule.version}::{resource_id}::sig-1",
        rule_id=rule.id,
        rule_version=rule.version,
        resource_id=resource_id,
        signal_id="sig-1",
        severity=rule.severity,
        context={"deny_reason": "example"},
    )


# ---------------------------------------------------------------------------
# Happy path - every shipped ActionType produces a valid Action
# ---------------------------------------------------------------------------


def test_builds_valid_action_for_tag_add_type() -> None:
    builder = ActionBuilder(action_types_by_name=_shipped_action_types())  # type: ignore[arg-type]
    rule = _rule("r1", "remediate.tag-add", parameters={"tag_name": "owner"})
    action = builder.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)
    assert action.action_type == "remediate.tag-add"
    assert action.operation is Operation.TAG
    assert action.target_resource_ref == "rid-1"
    assert action.mode is Mode.SHADOW
    assert action.citing_rules == ["r1"]
    assert action.rollback_ref.kind is RollbackKind.SNAPSHOT_RESTORE
    assert action.blast_radius.scope is BlastRadiusScope.RESOURCE
    assert action.action_type_ref is not None
    assert action.action_type_ref.name == "remediate.tag-add"
    assert action.action_type_ref.version == "1.1.0"
    assert action.action_type_ref.catalog_digest.startswith("sha256:")


def test_deterministic_action_id_across_replays() -> None:
    types = _shipped_action_types()
    rule = _rule("r1", "remediate.tag-add")
    b1 = ActionBuilder(action_types_by_name=types)  # type: ignore[arg-type]
    b2 = ActionBuilder(action_types_by_name=types)  # type: ignore[arg-type]
    a1 = b1.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)
    a2 = b2.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)
    assert a1.action_id == a2.action_id
    assert isinstance(a1.action_id, UUID)


def test_idempotency_key_derives_from_event_rule_resource() -> None:
    rule = _rule("r1", "remediate.tag-add")
    builder = ActionBuilder(action_types_by_name=_shipped_action_types())  # type: ignore[arg-type]
    action = builder.build_from_finding(
        event=_event(), finding=_finding(rule, resource_id="stg1"), rule=rule
    )
    assert action.idempotency_key == "e1::r1::stg1"


def test_finding_context_stays_out_of_action_params() -> None:
    """Finding context (e.g. ``deny_reason``) is audit-log data, not a
    template placeholder - the ActionBuilder MUST NOT inject it into
    ``Action.params`` or the renderer's scalar-only rule breaks."""
    rule = _rule("r1", "remediate.tag-add", parameters={"tag_name": "owner"})
    builder = ActionBuilder(action_types_by_name=_shipped_action_types())  # type: ignore[arg-type]
    action = builder.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)
    assert action.params == {"tag_name": "owner", "target_resource_ref": "rid-1"}
    assert "_finding_context" not in action.params


def test_builds_valid_action_from_t1_learned_action() -> None:
    builder = ActionBuilder(action_types_by_name=_shipped_action_types())  # type: ignore[arg-type]
    learned = LearnedAction(
        signature="learned-signature",
        rule_id="r1",
        action_type="remediate.tag-add",
        params={},
        incident_id="incident-1",
        success_rate=0.99,
        reuse_count=50,
    )

    action = builder.build_from_learned_action(
        event=_event(),
        learned=learned,
        target_resource_ref="resource-1",
    )

    assert action.action_type == "remediate.tag-add"
    assert action.target_resource_ref == "resource-1"
    assert action.idempotency_key == "e1::t1::learned-signature::resource-1"
    assert action.citing_rules == ["r1"]
    assert action.mode is Mode.SHADOW


def test_unknown_remediates_raises_action_build_error() -> None:
    rule = _rule("r1", "remediate.does-not-exist")
    builder = ActionBuilder(action_types_by_name=_shipped_action_types())  # type: ignore[arg-type]
    with pytest.raises(ActionBuildError, match="does-not-exist"):
        builder.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)


# ---------------------------------------------------------------------------
# Blast-radius mapping across the two computation modes
# ---------------------------------------------------------------------------


def test_static_bucket_blast_radius_maps_to_action_shape() -> None:
    """`remediate.tag-add` uses `static_enum` with `static_bucket: resource`."""
    rule = _rule("r1", "remediate.tag-add")
    builder = ActionBuilder(action_types_by_name=_shipped_action_types())  # type: ignore[arg-type]
    action = builder.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)
    assert action.blast_radius.scope is BlastRadiusScope.RESOURCE
    assert action.blast_radius.count == 1


def test_graph_derived_blast_radius_stays_unknown_until_simulated() -> None:
    """The authored maximum is not an observed affected-resource count."""
    rule = _rule("r1", "remediate.disable-public-access")
    builder = ActionBuilder(action_types_by_name=_shipped_action_types())  # type: ignore[arg-type]
    action = builder.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)
    assert action.blast_radius.count is None


# ---------------------------------------------------------------------------
# Stop-condition derivation
# ---------------------------------------------------------------------------


def test_stop_conditions_preserve_complete_action_type_contract() -> None:
    rule = _rule("r1", "remediate.tag-add")
    builder = ActionBuilder(action_types_by_name=_shipped_action_types())  # type: ignore[arg-type]
    action = builder.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)
    # `remediate.tag-add`'s first stop_condition is
    # `kind: provider_api_error_streak`.
    assert action.stop_condition == "provider_api_error_streak"
    assert action.stop_conditions == _shipped_action_types()["remediate.tag-add"].stop_conditions


def test_action_type_without_stop_conditions_raises(tmp_path: Path) -> None:
    """Defense-in-depth: the schema allows an empty stop_conditions list,
    but the builder refuses to synthesize a placeholder."""
    from fdai.rule_catalog.schema.action_type import load_action_type_from_mapping

    raw = {
        "schema_version": "1.0.0",
        "name": "remediate.custom-empty",
        "version": "1.0.0",
        "operation": "tag",
        "interfaces": ["ControlPlane"],
        "rollback_contract": "pr_revert",
        "default_mode": "shadow",
        "promotion_gate": {
            "min_shadow_days": 1,
            "min_samples": 1,
            "min_accuracy": 0.9,
            "max_policy_escapes": 0,
        },
        # deliberately no stop_conditions
    }
    action_type = load_action_type_from_mapping(
        raw, schema_registry=PackageResourceSchemaRegistry()
    )
    rule = _rule("r1", "remediate.custom-empty")
    builder = ActionBuilder(action_types_by_name={action_type.name: action_type})
    with pytest.raises(ActionBuildError, match="stop_conditions"):
        builder.build_from_finding(event=_event(), finding=_finding(rule), rule=rule)


def test_build_from_candidate_derives_catalog_safety_invariants() -> None:
    action_type = _shipped_action_types()["ops.restart-service"]
    builder = ActionBuilder(action_types_by_name={action_type.name: action_type})  # type: ignore[attr-defined]
    target = "resource:example/compute/vm-1"
    candidate = QualityCandidate(
        action_type=action_type.name,  # type: ignore[attr-defined]
        target_resource_ref=target,
        target_resource_type="compute.vm",
        params={
            "target_resource_ref": target,
            "restart_reason": "Health probe failed repeatedly.",
        },
        cited_rule_ids=("compute.restart.required",),
    )

    action = builder.build_from_candidate(event=_event(), candidate=candidate)

    assert action.mode is Mode.SHADOW
    assert action.rollback_ref.kind == action_type.rollback_contract  # type: ignore[attr-defined]
    assert action.stop_condition == action_type.stop_conditions[0].kind.value  # type: ignore[attr-defined]
    assert action.citing_rules == ["compute.restart.required"]


def test_build_from_candidate_rejects_invalid_arguments() -> None:
    action_type = _shipped_action_types()["ops.restart-service"]
    builder = ActionBuilder(action_types_by_name={action_type.name: action_type})  # type: ignore[attr-defined]
    candidate = QualityCandidate(
        action_type=action_type.name,  # type: ignore[attr-defined]
        target_resource_ref="resource:example/compute/vm-1",
        target_resource_type="compute.vm",
        params={"restart_reason": "too short"},
        cited_rule_ids=("compute.restart.required",),
    )

    with pytest.raises(ActionBuildError, match="argument_schema"):
        builder.build_from_candidate(event=_event(), candidate=candidate)


def _operator_event(
    *,
    extra_params: dict | None = None,
    workflow_action: dict[str, str] | None = None,
) -> Event:
    target = "resource:compute/vm/gpu-worker"
    params = {
        "artifact_ref": "python-task:gpu.health@1.0.0#" + "a" * 64,
        "target_resource_ref": target,
        "reason": "Run the governed GPU health task.",
        **(extra_params or {}),
    }
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000101",
            "idempotency_key": "operator-1::run-1",
            "correlation_id": "vm-task-example",
            "source": "operator_console",
            "event_type": "operator_request",
            "resource_ref": target,
            "payload": {
                "operator_request": {
                    "initiator_principal": "operator-1",
                    "action_type": "tool.run-python-on-vm",
                    "params": params,
                },
                **({"workflow_action": workflow_action} if workflow_action else {}),
            },
            "detected_at": "2026-07-15T00:00:00Z",
            "ingested_at": "2026-07-15T00:00:00Z",
            "mode": "shadow",
        }
    )


def test_build_from_operator_request_preserves_valid_arguments() -> None:
    action_type = _shipped_action_types()["tool.run-python-on-vm"]
    builder = ActionBuilder(action_types_by_name={action_type.name: action_type})  # type: ignore[attr-defined]

    action, rule = builder.build_from_operator_request(event=_operator_event())

    assert action.params["artifact_ref"].startswith("python-task:gpu.health@")
    assert action.target_resource_ref == action.params["target_resource_ref"]
    assert action.mode is Mode.SHADOW
    assert action.citing_rules == [rule.id]


def test_build_from_operator_request_preserves_workflow_lineage_outside_params() -> None:
    action_type = _shipped_action_types()["tool.run-python-on-vm"]
    builder = ActionBuilder(action_types_by_name={action_type.name: action_type})  # type: ignore[attr-defined]
    workflow_action = {
        "process_id": "process-1",
        "step_id": "run-task",
        "proposal_ref": "operator-1::run-1",
    }

    action, _rule = builder.build_from_operator_request(
        event=_operator_event(workflow_action=workflow_action)
    )

    assert action.workflow_action is not None
    assert action.workflow_action.model_dump() == {**workflow_action, "attempt": 1}
    assert "process_id" not in action.params


def test_build_from_operator_request_rejects_non_schema_arguments() -> None:
    action_type = _shipped_action_types()["tool.run-python-on-vm"]
    builder = ActionBuilder(action_types_by_name={action_type.name: action_type})  # type: ignore[attr-defined]

    with pytest.raises(ActionBuildError, match="argument_schema"):
        builder.build_from_operator_request(
            event=_operator_event(extra_params={"workflow_ref": "scheduled-gpu-task"})
        )


def test_operator_request_rejects_rule_violation_only_remediation() -> None:
    action_type = _shipped_action_types()["remediate.tag-add"]
    builder = ActionBuilder(action_types_by_name={action_type.name: action_type})  # type: ignore[attr-defined]
    event = _operator_event().model_copy(
        update={
            "payload": {
                "operator_request": {
                    "initiator_principal": "operator-1",
                    "action_type": "remediate.tag-add",
                    "params": {},
                }
            }
        }
    )

    with pytest.raises(ActionBuildError, match="does not allow operator_request triggers"):
        builder.build_from_operator_request(event=event)


def _readiness_remediation_event(
    *,
    action_type: str = "remediate.tag-add",
    params: dict[str, object] | None = None,
    target_revision: str = "inventory-revision-7",
) -> Event:
    target = "resource:storage/account/example"
    now = datetime(2026, 10, 15, tzinfo=UTC)
    request = ReadinessRemediationRequest.create(
        idempotency_key="orr-remediation:" + "a" * 32,
        action_type=action_type,
        target_resource_ref=target,
        target_revision=target_revision,
        params=params if params is not None else {},
        citing_rule_ids=("readiness.owner-tag.required",),
        evidence_refs=("evidence:orr:owner-tag",),
        submitter="handoff-owner",
        approver="operations-approver",
        approved_at=now,
        requested_at=now,
        severity="high",
    )
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000102",
            "idempotency_key": request.idempotency_key,
            "correlation_id": request.request_id,
            "source": "operational_readiness",
            "event_type": "readiness_remediation_request",
            "resource_ref": target,
            "payload": {"readiness_remediation_request": request.model_dump(mode="json")},
            "detected_at": now,
            "ingested_at": now,
            "mode": "shadow",
        }
    )


def _readiness_rules(action_type: str) -> dict[str, Rule]:
    rule = _rule("readiness.owner-tag.required", action_type)
    return {rule.id: rule}


def test_build_from_readiness_remediation_preserves_grounded_shadow_request() -> None:
    action_type = _shipped_action_types()["remediate.tag-add"]
    release = build_ontology_release(action_types=(action_type,))  # type: ignore[arg-type]
    builder = ActionBuilder(  # type: ignore[attr-defined]
        action_types_by_name={action_type.name: action_type},
        ontology_release=release,
        rules_by_id=_readiness_rules(action_type.name),
    )

    action, rule = builder.build_from_readiness_remediation(
        event=_readiness_remediation_event(target_revision=release.digest)
    )

    assert action.action_type == "remediate.tag-add"
    assert action.mode is Mode.SHADOW
    assert action.citing_rules == ["readiness.owner-tag.required"]
    assert action.params == {}
    assert action.target_resource_ref == "resource:storage/account/example"
    request = ReadinessRemediationRequest.model_validate(
        _readiness_remediation_event(target_revision=release.digest).payload[
            "readiness_remediation_request"
        ]
    )
    assert action.idempotency_key == request.request_id
    assert rule.id.startswith("operational-readiness.orr-remediation-")
    assert rule.id not in action.citing_rules
    assert rule.remediates == action.action_type


def test_build_from_readiness_remediation_rejects_operator_only_action_type() -> None:
    action_type = _shipped_action_types()["tool.run-investigation"]
    release = build_ontology_release(action_types=(action_type,))  # type: ignore[arg-type]
    builder = ActionBuilder(  # type: ignore[attr-defined]
        action_types_by_name={action_type.name: action_type},
        ontology_release=release,
    )

    with pytest.raises(ActionBuildError, match="does not allow rule_violation triggers"):
        builder.build_from_readiness_remediation(
            event=_readiness_remediation_event(
                action_type="tool.run-investigation",
                params={},
                target_revision=release.digest,
            )
        )


def test_build_from_readiness_remediation_rejects_unknown_cited_rule() -> None:
    action_type = _shipped_action_types()["remediate.tag-add"]
    release = build_ontology_release(action_types=(action_type,))  # type: ignore[arg-type]
    builder = ActionBuilder(  # type: ignore[attr-defined]
        action_types_by_name={action_type.name: action_type},
        ontology_release=release,
    )

    with pytest.raises(ActionBuildError, match="cited rule .* is not registered"):
        builder.build_from_readiness_remediation(
            event=_readiness_remediation_event(target_revision=release.digest)
        )


def test_build_from_readiness_remediation_rejects_mismatched_cited_rule() -> None:
    action_type = _shipped_action_types()["remediate.tag-add"]
    release = build_ontology_release(action_types=(action_type,))  # type: ignore[arg-type]
    builder = ActionBuilder(  # type: ignore[attr-defined]
        action_types_by_name={action_type.name: action_type},
        ontology_release=release,
        rules_by_id=_readiness_rules("remediate.tag-remove"),
    )

    with pytest.raises(ActionBuildError, match="does not remediate"):
        builder.build_from_readiness_remediation(
            event=_readiness_remediation_event(target_revision=release.digest)
        )


def test_build_from_readiness_remediation_rejects_invalid_arguments() -> None:
    action_type = _shipped_action_types()["remediate.tag-add"]
    release = build_ontology_release(action_types=(action_type,))  # type: ignore[arg-type]
    builder = ActionBuilder(  # type: ignore[attr-defined]
        action_types_by_name={action_type.name: action_type},
        ontology_release=release,
    )

    with pytest.raises(ActionBuildError, match="argument_schema"):
        builder.build_from_readiness_remediation(
            event=_readiness_remediation_event(
                params={"tag_name": "owner"},
                target_revision=release.digest,
            )
        )


def test_build_from_readiness_remediation_rejects_untrusted_event_source() -> None:
    action_type = _shipped_action_types()["remediate.tag-add"]
    release = build_ontology_release(action_types=(action_type,))  # type: ignore[arg-type]
    builder = ActionBuilder(  # type: ignore[attr-defined]
        action_types_by_name={action_type.name: action_type},
        ontology_release=release,
    )
    event = _readiness_remediation_event().model_copy(update={"source": "example"})

    with pytest.raises(ActionBuildError, match="source or type is invalid"):
        builder.build_from_readiness_remediation(event=event)


def test_build_from_readiness_remediation_rejects_idempotency_identity_mismatch() -> None:
    action_type = _shipped_action_types()["remediate.tag-add"]
    release = build_ontology_release(action_types=(action_type,))  # type: ignore[arg-type]
    builder = ActionBuilder(  # type: ignore[attr-defined]
        action_types_by_name={action_type.name: action_type},
        ontology_release=release,
    )
    event = _readiness_remediation_event(target_revision=release.digest).model_copy(
        update={"idempotency_key": "different-envelope-key"}
    )

    with pytest.raises(ActionBuildError, match="idempotency identity does not match"):
        builder.build_from_readiness_remediation(event=event)


def test_build_from_readiness_remediation_rejects_action_outside_active_release() -> None:
    action_type = _shipped_action_types()["remediate.tag-add"]
    release = build_ontology_release(action_types=(action_type,))  # type: ignore[arg-type]
    mismatched = action_type.model_copy(update={"version": "9.9.9"})
    builder = ActionBuilder(  # type: ignore[attr-defined]
        action_types_by_name={mismatched.name: mismatched},
        ontology_release=release,
    )

    with pytest.raises(ActionBuildError, match="outside the active release"):
        builder.build_from_readiness_remediation(
            event=_readiness_remediation_event(target_revision=release.digest)
        )


def test_build_from_readiness_remediation_rejects_stale_ontology_release() -> None:
    action_type = _shipped_action_types()["remediate.tag-add"]
    release = build_ontology_release(action_types=(action_type,))  # type: ignore[arg-type]
    builder = ActionBuilder(  # type: ignore[attr-defined]
        action_types_by_name={action_type.name: action_type},
        ontology_release=release,
    )

    with pytest.raises(ActionBuildError, match="target revision is stale"):
        builder.build_from_readiness_remediation(event=_readiness_remediation_event())


def test_operator_action_idempotency_key_stays_within_vm_request_bound() -> None:
    action_type = _shipped_action_types()["tool.run-python-on-vm"]
    builder = ActionBuilder(action_types_by_name={action_type.name: action_type})  # type: ignore[attr-defined]
    event = _operator_event().model_copy(update={"idempotency_key": "x" * 200})

    action, _rule = builder.build_from_operator_request(event=event)

    assert len(action.idempotency_key) <= 200


def test_candidate_and_learned_action_error_branches() -> None:
    action_type = _shipped_action_types()["remediate.tag-add"]
    builder = ActionBuilder(
        action_types_by_name={action_type.name: action_type},  # type: ignore[attr-defined]
        clock=lambda: datetime(2026, 7, 5, 8, 0, tzinfo=UTC),
    )

    for action_name, rules, params, match in (
        ("unknown.action", ("r1",), {}, "is not registered"),
        ("remediate.tag-add", (), {}, "MUST cite at least one catalog rule"),
        ("remediate.tag-add", ("r1",), "not-a-dict", "params MUST be an object"),
    ):
        with pytest.raises(ActionBuildError, match=match):
            builder.build_from_candidate(
                event=_event(),
                candidate=QualityCandidate(
                    action_type=action_name,
                    target_resource_ref="rid-1",
                    target_resource_type="object-storage",
                    params=params,  # type: ignore[arg-type]
                    cited_rule_ids=rules,
                ),
            )

    for action_name, target_ref, match in (
        ("unknown.action", "rid-1", "is not registered"),
        ("remediate.tag-add", "", "target_resource_ref MUST be non-empty"),
    ):
        with pytest.raises(ActionBuildError, match=match):
            builder.build_from_learned_action(
                event=_event(),
                learned=LearnedAction(
                    signature="sig",
                    rule_id="r1",
                    action_type=action_name,
                    params={},
                    incident_id="inc-1",
                    success_rate=0.99,
                    reuse_count=10,
                ),
                target_resource_ref=target_ref,
            )


def test_operator_request_and_workflow_validation_branches() -> None:
    vm_type = _shipped_action_types()["tool.run-python-on-vm"]
    no_schema_type = vm_type.model_copy(  # type: ignore[attr-defined]
        update={"name": "custom.no-schema", "argument_schema": None, "blast_radius": None}
    )
    builder = ActionBuilder(
        action_types_by_name={
            vm_type.name: vm_type,  # type: ignore[attr-defined]
            "custom.no-schema": no_schema_type,
        }
    )

    base = _operator_event()
    with pytest.raises(ActionBuildError, match="no normalized operator_request"):
        builder.build_from_operator_request(event=base.model_copy(update={"payload": {}}))
    with pytest.raises(ActionBuildError, match="resource_ref MUST be non-empty"):
        builder.build_from_operator_request(event=base.model_copy(update={"resource_ref": None}))

    for op_req, match in (
        ({"action_type": "", "initiator_principal": "op", "params": {}}, "action_type MUST"),
        (
            {"action_type": vm_type.name, "initiator_principal": "", "params": {}},  # type: ignore[attr-defined]
            "initiator_",
        ),
        (
            {"action_type": vm_type.name, "initiator_principal": "op", "params": "bad"},  # type: ignore[attr-defined]
            "params MUST",
        ),
        ({"action_type": "unknown", "initiator_principal": "op", "params": {}}, "is unknown"),
        (
            {"action_type": "custom.no-schema", "initiator_principal": "op", "params": {"k": "v"}},
            "has no argument_schema; params MUST be empty",
        ),
    ):
        with pytest.raises(ActionBuildError, match=match):
            builder.build_from_operator_request(
                event=base.model_copy(update={"payload": {"operator_request": op_req}})
            )

    ok_no_schema, rule = builder.build_from_operator_request(
        event=base.model_copy(
            update={
                "payload": {
                    "operator_request": {
                        "action_type": "custom.no-schema",
                        "initiator_principal": "op",
                        "params": {},
                    },
                    "resource": {"resource_type": "compute.vm"},
                }
            }
        )
    )
    assert ok_no_schema.blast_radius.count == 1
    assert rule.resource_type == "compute.vm"

    with pytest.raises(ActionBuildError, match="workflow_action is malformed"):
        builder.build_from_operator_request(
            event=_operator_event(workflow_action={"process_id": ""})
        )
    with pytest.raises(ActionBuildError, match="proposal_ref MUST match"):
        builder.build_from_operator_request(
            event=_operator_event(
                workflow_action={
                    "process_id": "p1",
                    "step_id": "s1",
                    "proposal_ref": "wrong-ref",
                }
            )
        )


def test_readiness_remediation_remaining_validation_branches() -> None:
    action_type = _shipped_action_types()["remediate.tag-add"]
    release = build_ontology_release(action_types=(action_type,))  # type: ignore[arg-type]
    builder = ActionBuilder(  # type: ignore[attr-defined]
        action_types_by_name={action_type.name: action_type},
        ontology_release=release,
        rules_by_id=_readiness_rules(action_type.name),
    )
    event = _readiness_remediation_event(target_revision=release.digest)

    with pytest.raises(ActionBuildError, match="MUST remain in shadow mode"):
        builder.build_from_readiness_remediation(
            event=event.model_copy(update={"mode": Mode.ENFORCE})
        )
    with pytest.raises(ActionBuildError, match="request is malformed"):
        builder.build_from_readiness_remediation(
            event=event.model_copy(update={"payload": {"readiness_remediation_request": "bad"}})
        )
    with pytest.raises(ActionBuildError, match="target does not match"):
        builder.build_from_readiness_remediation(
            event=event.model_copy(update={"resource_ref": "resource:other"})
        )
    no_release_builder = ActionBuilder(
        action_types_by_name={action_type.name: action_type}  # type: ignore[attr-defined]
    )
    with pytest.raises(ActionBuildError, match="requires an active ontology release"):
        no_release_builder.build_from_readiness_remediation(event=event)

    empty_builder = ActionBuilder(action_types_by_name={}, ontology_release=release)
    with pytest.raises(ActionBuildError, match="is unknown"):
        empty_builder.build_from_readiness_remediation(event=event)

    with_resource = event.model_copy(
        update={
            "payload": {
                **event.payload,
                "resource": {"resource_type": "storage.account"},
            }
        }
    )
    _action, rule = builder.build_from_readiness_remediation(event=with_resource)
    assert rule.resource_type == "storage.account"
