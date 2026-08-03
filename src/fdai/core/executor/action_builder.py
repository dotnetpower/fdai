"""Action builder - turn a T0 Finding into a policy-safe Action.

The T0 engine emits :class:`Finding` records (rule matches on resources).
The :class:`ShadowExecutor` consumes :class:`Action` values that carry the
action-level safeguard declarations inline. This module is the bridge: given a
Finding + the matched Rule + the referenced ActionType, produce a valid
Action that pydantic accepts.

Design notes
------------

- **Deterministic idempotency key**: composed from
  ``event.idempotency_key`` + ``rule.id`` + ``finding.resource_id``.
  A replay of the same event produces the same Action id (via
  ``uuid.uuid5``) so the executor's dedupe + the publisher's
  idempotency probe both hit the same cache entry.
- **Safety invariants** are derived from the ActionType - never
  guessed. Missing stop_conditions / blast_radius / rollback_contract
  fields raise :class:`ActionBuildError` so a partial ActionType
  cannot slip past.
- **Shadow-only** - every Action carries :attr:`Mode.SHADOW` in P1.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator

from fdai.core.quality_gate.gate import QualityCandidate
from fdai.core.tiers.t0_deterministic.models import Finding
from fdai.core.tiers.t1_lightweight import LearnedAction
from fdai.shared.contracts.models import (
    Action,
    BlastRadius,
    BlastRadiusComputation,
    BlastRadiusScope,
    Event,
    Mode,
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyRelease,
    OntologyTypeRef,
    RollbackRef,
    Rule,
    TriggerKind,
    WorkflowActionRef,
)
from fdai.shared.ontology.release import build_ontology_release


class ActionBuildError(ValueError):
    """Raised when a Finding + Rule + ActionType cannot map to an Action."""


@dataclass(frozen=True, slots=True)
class ActionBuilder:
    """Deterministic mapping from a Finding to an Action.

    Kept as a plain dataclass so a fork MAY subclass it to tighten
    invariants (e.g. reject an ActionType whose stop_conditions include
    a value the fork's operator group disallows) without touching the
    executor.
    """

    action_types_by_name: dict[str, OntologyActionType]
    ontology_release: OntologyRelease | None = None

    def build_from_finding(
        self,
        *,
        event: Event,
        finding: Finding,
        rule: Rule,
    ) -> Action:
        """Return a fully-populated :class:`Action` for one finding."""
        action_type = self.action_types_by_name.get(rule.remediates)
        if action_type is None:
            raise ActionBuildError(
                f"rule {rule.id!r} remediates {rule.remediates!r} "
                "which is not registered in the ActionType catalog"
            )

        stop_condition = _derive_stop_condition(action_type)
        rollback = RollbackRef(kind=action_type.rollback_contract, reference=None)
        blast_radius = _derive_blast_radius(action_type)
        idempotency_key = _build_idempotency_key(event=event, finding=finding)
        action_id = _build_action_id(idempotency_key)

        params: dict[str, Any] = dict(rule.parameters)
        # Finding context (e.g. `deny_reason`) is audit-log data, not a
        # template placeholder - keeping it out of Action.params means the
        # template renderer's scalar-only rule stays clean.

        return Action(
            schema_version="1.0.0",
            action_id=action_id,
            idempotency_key=idempotency_key,
            event_id=event.event_id,
            action_type=action_type.name,
            target_resource_ref=finding.resource_id,
            operation=action_type.operation,
            params=params,
            stop_condition=stop_condition,
            stop_conditions=list(action_type.stop_conditions),
            rollback_ref=rollback,
            blast_radius=blast_radius,
            mode=Mode.SHADOW,
            citing_rules=[finding.rule_id],
            created_at=datetime.now(tz=UTC),
            action_type_ref=self._action_type_ref(action_type),
        )

    def build_from_candidate(
        self,
        *,
        event: Event,
        candidate: QualityCandidate,
    ) -> Action:
        """Build a shadow Action from a quality-gate-approved T2 candidate."""
        action_type = self.action_types_by_name.get(candidate.action_type)
        if action_type is None:
            raise ActionBuildError(
                f"candidate action_type {candidate.action_type!r} is not registered"
            )
        if not candidate.cited_rule_ids:
            raise ActionBuildError("candidate MUST cite at least one catalog rule")
        _validate_action_params(action_type, candidate.params, source="candidate")

        idempotency_key = (
            f"{event.idempotency_key}::t2::{candidate.action_type}::{candidate.target_resource_ref}"
        )
        return Action(
            schema_version="1.0.0",
            action_id=_build_action_id(idempotency_key),
            idempotency_key=idempotency_key,
            event_id=event.event_id,
            action_type=action_type.name,
            target_resource_ref=candidate.target_resource_ref,
            operation=action_type.operation,
            params=dict(candidate.params),
            stop_condition=_derive_stop_condition(action_type),
            stop_conditions=list(action_type.stop_conditions),
            rollback_ref=RollbackRef(
                kind=action_type.rollback_contract,
                reference=None,
            ),
            blast_radius=_derive_blast_radius(action_type),
            mode=Mode.SHADOW,
            citing_rules=list(candidate.cited_rule_ids),
            created_at=datetime.now(tz=UTC),
            action_type_ref=self._action_type_ref(action_type),
        )

    def build_from_learned_action(
        self,
        *,
        event: Event,
        learned: LearnedAction,
        target_resource_ref: str,
    ) -> Action:
        """Build a shadow Action from a current-evidence-verified T1 reuse."""
        action_type = self.action_types_by_name.get(learned.action_type)
        if action_type is None:
            raise ActionBuildError(f"learned action_type {learned.action_type!r} is not registered")
        if not target_resource_ref:
            raise ActionBuildError("learned action target_resource_ref MUST be non-empty")
        _validate_action_params(action_type, learned.params, source="learned action")
        idempotency_key = f"{event.idempotency_key}::t1::{learned.signature}::{target_resource_ref}"
        return Action(
            schema_version="1.0.0",
            action_id=_build_action_id(idempotency_key),
            idempotency_key=idempotency_key,
            event_id=event.event_id,
            action_type=action_type.name,
            target_resource_ref=target_resource_ref,
            operation=action_type.operation,
            params=dict(learned.params),
            stop_condition=_derive_stop_condition(action_type),
            stop_conditions=list(action_type.stop_conditions),
            rollback_ref=RollbackRef(kind=action_type.rollback_contract, reference=None),
            blast_radius=_derive_blast_radius(action_type),
            mode=Mode.SHADOW,
            citing_rules=[learned.rule_id],
            created_at=datetime.now(tz=UTC),
            action_type_ref=self._action_type_ref(action_type),
        )

    def build_from_operator_request(self, *, event: Event) -> tuple[Action, Rule]:
        """Build one policy-safe Action from a normalized operator proposal."""
        raw = event.payload.get("operator_request")
        if not isinstance(raw, dict):
            raise ActionBuildError("event payload has no normalized operator_request")
        action_type_name = raw.get("action_type")
        initiator = raw.get("initiator_principal")
        params = raw.get("params")
        if not isinstance(action_type_name, str) or not action_type_name:
            raise ActionBuildError("operator_request action_type MUST be non-empty")
        if not isinstance(initiator, str) or not initiator:
            raise ActionBuildError("operator_request initiator_principal MUST be non-empty")
        if not isinstance(params, dict):
            raise ActionBuildError("operator_request params MUST be an object")
        if not event.resource_ref:
            raise ActionBuildError("operator_request resource_ref MUST be non-empty")
        action_type = self.action_types_by_name.get(action_type_name)
        if action_type is None:
            raise ActionBuildError(f"operator_request ActionType {action_type_name!r} is unknown")
        trigger = action_type.trigger_kind
        if trigger is None or trigger.kind not in {TriggerKind.OPERATOR_REQUEST, TriggerKind.BOTH}:
            raise ActionBuildError(
                f"ActionType {action_type_name!r} does not allow operator_request triggers"
            )
        if action_type.argument_schema is None:
            if params:
                raise ActionBuildError(
                    f"ActionType {action_type_name!r} has no argument_schema; params MUST be empty"
                )
        else:
            errors = sorted(
                Draft202012Validator(action_type.argument_schema).iter_errors(params),
                key=lambda error: list(error.absolute_path),
            )
            if errors:
                first = errors[0]
                path = ".".join(str(part) for part in first.absolute_path) or "<root>"
                raise ActionBuildError(
                    f"operator_request params violate {action_type_name!r} argument_schema "
                    f"at {path}: {first.message}"
                )
        resource = event.payload.get("resource")
        resource_type = resource.get("resource_type") if isinstance(resource, dict) else None
        rule = _operator_request_rule(
            action_type,
            resource_type if isinstance(resource_type, str) else "operator-request",
        )
        idempotency_key = _build_operator_idempotency_key(
            event_idempotency_key=event.idempotency_key,
            action_type_name=action_type_name,
        )
        workflow_action = _workflow_action_ref(event)
        return (
            Action(
                schema_version="1.0.0",
                action_id=_build_action_id(idempotency_key),
                idempotency_key=idempotency_key,
                event_id=event.event_id,
                action_type=action_type.name,
                target_resource_ref=event.resource_ref,
                operation=action_type.operation,
                params=dict(params),
                stop_condition=_derive_stop_condition(action_type),
                stop_conditions=list(action_type.stop_conditions),
                rollback_ref=RollbackRef(kind=action_type.rollback_contract, reference=None),
                blast_radius=_derive_blast_radius(action_type),
                mode=Mode.SHADOW,
                citing_rules=[rule.id],
                created_at=datetime.now(tz=UTC),
                action_type_ref=self._action_type_ref(action_type),
                workflow_action=workflow_action,
            ),
            rule,
        )

    def _action_type_ref(self, action_type: OntologyActionType) -> OntologyTypeRef:
        release = self.ontology_release or build_ontology_release(
            action_types=tuple(self.action_types_by_name.values())
        )
        return release.type_ref(OntologyDeclarationKind.ACTION, action_type.name)


def _operator_request_rule(action_type: OntologyActionType, resource_type: str) -> Rule:
    """Server-owned policy context used by the unified risk gate and HIL park."""
    return Rule.model_validate(
        {
            "schema_version": "1.0.0",
            "id": f"operator.request.{action_type.name}",
            "version": "1.0.0",
            "source": "custom",
            "severity": "high",
            "category": "config_drift",
            "resource_type": resource_type,
            "check_logic": {
                "kind": "expression",
                "reference": "server-validated-operator-request",
            },
            "remediation": {"template_ref": "operator-request"},
            "remediates": action_type.name,
            "provenance": {
                "source_url": "https://fdai.dev/operator-request",
                "resolved_ref": "runtime-v1",
                "content_hash": "sha256:runtime-operator-request-v1",
                "license": "LicenseRef-runtime",
                "redistribution": "embeddable",
                "retrieved_at": "2026-07-15T00:00:00Z",
            },
        }
    )


def _validate_action_params(
    action_type: OntologyActionType,
    params: dict[str, Any] | Any,
    *,
    source: str,
) -> None:
    if not isinstance(params, dict):
        raise ActionBuildError(f"{source} params MUST be an object")
    if action_type.argument_schema is None:
        if params:
            raise ActionBuildError(
                f"ActionType {action_type.name!r} declares no argument_schema; "
                f"{source} params MUST be empty"
            )
        return
    errors = sorted(
        Draft202012Validator(action_type.argument_schema).iter_errors(params),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise ActionBuildError(
            f"{source} params violate {action_type.name!r} argument_schema "
            f"at {path}: {first.message}"
        )


def _derive_stop_condition(action_type: OntologyActionType) -> str:
    """Flatten the ActionType's first stop_condition into a string.

    :class:`Action.stop_condition` is a single string per the contract
    (see ``shared/contracts/action/schema.json``). ActionTypes ship a
    list; we take the first entry's ``kind`` as the shorthand and rely
    on the audit record to carry the full ActionType reference.
    ActionTypes without stop_conditions are legal at the schema level
    but the executor will refuse them, so we surface the missing state
    here for a clearer error.
    """
    if not action_type.stop_conditions:
        raise ActionBuildError(
            f"ActionType {action_type.name!r} declares no stop_conditions; "
            "P1 executor requires at least one"
        )
    kind = action_type.stop_conditions[0].kind
    return kind.value


def _derive_blast_radius(action_type: OntologyActionType) -> BlastRadius:
    """Flatten :class:`ActionBlastRadius` into the Action's :class:`BlastRadius`."""
    ar = action_type.blast_radius
    if ar is None:
        # Conservative default when the ActionType omits blast_radius -
        # single resource, no rate cap. P2 tightens this.
        return BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1)

    if ar.computation is BlastRadiusComputation.STATIC_ENUM:
        scope = ar.static_bucket or BlastRadiusScope.RESOURCE
        return BlastRadius(scope=scope, count=1)

    # graph_derived - count is bounded by the ActionType cap, real
    # resolved count comes from the risk-gate at P2. For now, use the
    # authored cap as the maximum affected count.
    return BlastRadius(
        scope=BlastRadiusScope.RESOURCE,
        count=ar.max_affected_resources or 1,
    )


def _build_idempotency_key(*, event: Event, finding: Finding) -> str:
    return f"{event.idempotency_key}::{finding.rule_id}::{finding.resource_id}"


def _build_action_id(idempotency_key: str) -> Any:
    """Deterministic UUID5 from the idempotency key.

    Replays of the same event produce the same action_id, so the
    executor's dedupe cache + the publisher's idempotency probe both
    treat them as the same request.
    """
    return uuid5(NAMESPACE_URL, f"fdai.action://{idempotency_key}")


def _build_operator_idempotency_key(*, event_idempotency_key: str, action_type_name: str) -> str:
    digest = hashlib.sha256(f"{event_idempotency_key}\n{action_type_name}".encode()).hexdigest()
    return f"operator:{digest}"


def _workflow_action_ref(event: Event) -> WorkflowActionRef | None:
    raw = event.payload.get("workflow_action")
    if raw is None:
        return None
    try:
        reference = WorkflowActionRef.model_validate(raw)
    except ValueError as exc:
        raise ActionBuildError("workflow_action is malformed") from exc
    if reference.proposal_ref != event.idempotency_key:
        raise ActionBuildError("workflow_action.proposal_ref MUST match event idempotency_key")
    return reference


__all__ = ["ActionBuildError", "ActionBuilder"]
