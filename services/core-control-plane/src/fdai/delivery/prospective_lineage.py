"""Finalize, materialize, and gate exact prospective operational lineage."""

from __future__ import annotations

import json
from collections.abc import Mapping

from jsonschema import Draft202012Validator

from fdai.core.decision_case import ActionArguments, ObjectiveEffect
from fdai.core.ontology_platform import (
    ActionArgumentBinding,
    MutationEffect,
    MutationEffectKind,
    build_mutation_plan,
)
from fdai.core.operational_planning import (
    KineticActionProposal,
    OperationalPlan,
    SpecialistPlanningProjection,
)
from fdai.core.operational_planning.hypothesis_lineage import (
    OperationalHypothesisLineageProjector,
    OperationalProspectiveLineage,
)
from fdai.core.operational_planning.prospective_lineage import (
    FinalizedProspectiveLineage,
    ProspectiveLineage,
)
from fdai.delivery.kinetic_proposal import StateStoreKineticActionProposalStore
from fdai.shared.contracts.models import (
    ActionLockScope,
    ActionTransactionMode,
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyRelease,
)
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_store import StateStore

_MATERIALIZED_PREFIX = "operational-planning:prospective-lineage:materialized:"
_PROPOSAL_PREFIX = "operational-planning:prospective-lineage:proposal:"
_SAGA_PREFIX = "operational-planning:prospective-lineage:saga:"


class OperationalPlanningProspectiveFinalizer:
    """Build the exact proposal and prospective records for Odin's finalized option."""

    def __init__(
        self,
        *,
        proposal_store: StateStoreKineticActionProposalStore,
        ontology_store: OntologyInstanceStore,
        ontology_release: OntologyRelease,
        action_types: tuple[OntologyActionType, ...],
    ) -> None:
        self._proposal_store = proposal_store
        self._ontology_store = ontology_store
        self._ontology_release = ontology_release
        self._action_types = {item.name: item for item in action_types}

    async def finalize(
        self,
        projection: SpecialistPlanningProjection,
    ) -> FinalizedProspectiveLineage:
        """Compile and commit one exact V2 proposal without granting execution authority."""

        plan = projection.plan
        selected_id = plan.selection.selected_option_id
        selected = next(
            (option for option in plan.decision_case.options if option.option_id == selected_id),
            None,
        )
        if (
            not plan.complete
            or selected is None
            or selected.action_type is None
            or selected.arguments is None
        ):
            raise ValueError("finalized operational plan lacks exact selected arguments")
        action_type = self._action_types.get(selected.action_type)
        if action_type is None or action_type.argument_schema is None:
            raise ValueError("selected ActionType lacks a reviewed argument schema")
        arguments = selected.arguments.values()
        errors = sorted(
            Draft202012Validator(action_type.argument_schema).iter_errors(arguments),
            key=lambda error: list(error.path),
        )
        if errors:
            raise ValueError(f"selected action arguments are invalid: {errors[0].message}")
        target = await self._ontology_store.get_object(plan.target_resource_id)
        if target is None or target.type_ref is None or target.revision < 1:
            raise ValueError("prospective lineage target lacks an exact ontology revision")
        action_type_ref = self._ontology_release.type_ref(
            OntologyDeclarationKind.ACTION,
            action_type.name,
        )
        mutation_plan = build_mutation_plan(
            action_type_ref=action_type_ref,
            planner_ref=f"forseti:{plan.logic_release_digest}",
            targets=(target,),
            effects=(
                MutationEffect(
                    kind=MutationEffectKind.PROVIDER_COMMAND,
                    target_id=target.id,
                    command_ref=f"action-type:{action_type.name}@{action_type.version}:apply",
                ),
            ),
            rollback_effects=(
                MutationEffect(
                    kind=MutationEffectKind.PROVIDER_COMMAND,
                    target_id=target.id,
                    command_ref=(
                        f"action-type:{action_type.name}@{action_type.version}:"
                        f"rollback:{action_type.rollback_contract.value}"
                    ),
                ),
            ),
            expected_effects=tuple(
                MutationEffect(
                    kind=MutationEffectKind.EXPECTED_PROPERTY,
                    target_id=target.id,
                    property_name=effect.metric,
                    value={"min": effect.expected_min, "max": effect.expected_max},
                )
                for effect in selected.effects
            ),
            created_at=plan.decision_case.created_at,
            max_affected_objects=1,
            schema_version="2.0.0",
            arguments_digest=selected.arguments.arguments_digest,
            argument_bindings=_argument_bindings(selected.arguments),
            transaction_mode=ActionTransactionMode.SAGA,
            lock_scope=ActionLockScope.TARGET,
            lock_keys=(f"ontology-target:{target.id}",),
            irreversible=action_type.irreversible,
            operational_plan_ref=plan.plan_id,
        )
        proposal = await self._proposal_store.commit(
            operational_plan=plan,
            mutation_plan=mutation_plan,
            arguments=arguments,
            created_at=mutation_plan.created_at,
        )
        lineage = build_prospective_lineage_records(plan=plan, proposal=proposal)
        envelope = ProspectiveLineage.create(lineage=lineage, proposal=proposal)
        return FinalizedProspectiveLineage(
            projection=projection,
            proposal=proposal,
            lineage=lineage,
            envelope=envelope,
        )


class StateStoreProspectiveLineageMaterializer:
    """Materialize the exact subgraph and join it with Saga's matching audit."""

    def __init__(
        self,
        *,
        state_store: StateStore,
        proposal_store: StateStoreKineticActionProposalStore,
        ontology_store: OntologyInstanceStore,
    ) -> None:
        self._state_store = state_store
        self._proposal_store = proposal_store
        self._ontology_store = ontology_store
        self._projector = OperationalHypothesisLineageProjector(store=ontology_store)

    async def materialize(self, envelope: ProspectiveLineage) -> bool:
        resolved = await self._proposal_store.resolve_plan(envelope.operational_plan_id)
        if resolved is None:
            raise ValueError("prospective lineage has no exact durable proposal")
        plan, proposal = resolved
        lineage = build_prospective_lineage_records(plan=plan, proposal=proposal)
        rebuilt = ProspectiveLineage.create(lineage=lineage, proposal=proposal)
        if rebuilt != envelope:
            raise ValueError("prospective lineage envelope does not match durable artifacts")
        await self._projector.project_prospective(lineage)
        envelope_record = _envelope_record(envelope)
        existing_envelope = await self._ontology_store.get_object(envelope.id)
        if existing_envelope is None:
            await self._ontology_store.replace_subgraph(
                objects=(envelope_record,),
                links=(),
            )
        elif existing_envelope.object_type != envelope_record.object_type or dict(
            existing_envelope.properties
        ) != dict(envelope_record.properties):
            raise ValueError("prospective lineage ontology envelope changed")
        materialized = {
            "kind": "prospective_lineage.materialized",
            "lineage_id": envelope.id,
            "proposal_id": envelope.proposal_id,
            "subgraph_digest": envelope.subgraph_digest,
        }
        created = await self._state_store.write_state_with_audit_if_absent(
            f"{_MATERIALIZED_PREFIX}{envelope.id}",
            materialized,
            {
                "action_kind": "prospective_lineage.materialized",
                "actor": "Muninn",
                **materialized,
            },
        )
        await self._write_exact(
            f"{_PROPOSAL_PREFIX}{envelope.proposal_id}",
            materialized,
        )
        return created

    async def seal_saga(self, *, lineage_id: str, subgraph_digest: str) -> bool:
        return await self._state_store.write_state_with_audit_if_absent(
            f"{_SAGA_PREFIX}{lineage_id}",
            {
                "kind": "prospective_lineage.saga_sealed",
                "lineage_id": lineage_id,
                "subgraph_digest": subgraph_digest,
            },
            {
                "action_kind": "prospective_lineage.saga_sealed",
                "actor": "Saga",
                "lineage_id": lineage_id,
                "subgraph_digest": subgraph_digest,
            },
        )

    async def ready(self, proposal_id: str) -> bool:
        return await _ready(self._state_store, proposal_id)

    async def _write_exact(self, key: str, value: Mapping[str, object]) -> None:
        if await self._state_store.write_state_if_absent(key, value):
            return
        existing = await self._state_store.read_state(key)
        if existing is None or dict(existing) != dict(value):
            raise ValueError("prospective lineage proposal index conflicts")


class StateStoreProspectiveLineageReadinessReader:
    """Read the joined Muninn materialization and Saga seal."""

    def __init__(self, state_store: StateStore) -> None:
        self._state_store = state_store

    async def ready(self, proposal_id: str) -> bool:
        return await _ready(self._state_store, proposal_id)


async def _ready(state_store: StateStore, proposal_id: str) -> bool:
    index = await state_store.read_state(f"{_PROPOSAL_PREFIX}{proposal_id}")
    if index is None:
        return False
    lineage_id = str(index.get("lineage_id") or "")
    subgraph_digest = str(index.get("subgraph_digest") or "")
    materialized = await state_store.read_state(f"{_MATERIALIZED_PREFIX}{lineage_id}")
    saga = await state_store.read_state(f"{_SAGA_PREFIX}{lineage_id}")
    return (
        materialized is not None
        and saga is not None
        and materialized.get("proposal_id") == proposal_id
        and materialized.get("subgraph_digest") == subgraph_digest
        and saga.get("subgraph_digest") == subgraph_digest
    )


def build_prospective_lineage_records(
    *,
    plan: OperationalPlan,
    proposal: KineticActionProposal,
) -> OperationalProspectiveLineage:
    """Build the exact pre-execution records shared by materialization and closure."""

    selected = next(
        (
            option
            for option in plan.decision_case.options
            if option.option_id == plan.selection.selected_option_id
        ),
        None,
    )
    if selected is None or selected.action_type is None:
        raise ValueError("prospective lineage requires one selected ActionType option")
    if (
        proposal.operational_plan_id != plan.plan_id
        or proposal.selected_option_id != selected.option_id
    ):
        raise ValueError("prospective lineage proposal does not match selected plan")
    baseline_by_objective = {
        effect.objective_id: effect for effect in plan.decision_case.no_action_effects
    }
    expected_effects = tuple(
        OntologyObjectRecord(
            id=_lineage_id(
                "expected-effect",
                plan.plan_id,
                selected.option_id,
                effect.objective_id,
            ),
            object_type="ExpectedEffect",
            properties={
                "id": _lineage_id(
                    "expected-effect",
                    plan.plan_id,
                    selected.option_id,
                    effect.objective_id,
                ),
                "metric": effect.metric,
                "direction": _direction(effect, baseline_by_objective.get(effect.objective_id)),
                "lower_bound": effect.expected_min,
                "upper_bound": effect.expected_max,
                "window_seconds": effect.observation_window_seconds,
                "uncertainty": 1.0 - effect.confidence,
                "predictor_version": plan.logic_release_digest,
                "created_at": plan.decision_case.created_at,
            },
        )
        for effect in selected.effects
    )
    case = OntologyObjectRecord(
        id=plan.decision_case.case_id,
        object_type="DecisionCase",
        properties={
            "id": plan.decision_case.case_id,
            "target_ref": plan.target_resource_id,
            "evidence_cutoff": plan.context_cutoff,
            "context_digest": plan.context_digest,
            "no_action_baseline": {
                "effects": [
                    _effect_values(effect) for effect in plan.decision_case.no_action_effects
                ]
            },
            "uncertainty": max(1.0 - effect.confidence for effect in selected.effects),
            "status": "selected",
            "created_at": plan.decision_case.created_at,
        },
    )
    option = OntologyObjectRecord(
        id=selected.option_id,
        object_type="ActionOption",
        properties={
            "id": selected.option_id,
            "decision_case_id": case.id,
            "action_type_ref": selected.action_type,
            "arguments": {
                "digest": proposal.arguments_digest,
                "projection": {
                    binding.name: json.loads(binding.safe_value_json)
                    for binding in proposal.plan.argument_bindings
                },
                "bindings": [
                    binding.model_dump(mode="json") for binding in proposal.plan.argument_bindings
                ],
            },
            "expected_effect_refs": [item.id for item in expected_effects],
            "preconditions": list(
                dict.fromkeys(
                    (
                        *proposal.plan.read_set_receipt_digests,
                        *proposal.plan.criterion_receipt_digests,
                    )
                )
            ),
            "option_kind": "intervention",
        },
    )
    return OperationalProspectiveLineage(
        decision_case=case,
        action_option=option,
        expected_effects=expected_effects,
    )


def _argument_bindings(arguments: ActionArguments) -> tuple[ActionArgumentBinding, ...]:
    return tuple(
        ActionArgumentBinding(
            name=binding.name,
            value_digest=binding.value_digest,
            redacted=binding.redacted,
            safe_value_json=binding.safe_value_json,
        )
        for binding in arguments.bindings
    )


def _envelope_record(envelope: ProspectiveLineage) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=envelope.id,
        object_type="ProspectiveLineage",
        properties=envelope.model_dump(mode="json", exclude={"schema_version"}),
    )


def _effect_values(effect: ObjectiveEffect) -> dict[str, object]:
    return {
        "objective_id": effect.objective_id,
        "metric": effect.metric,
        "expected_min": effect.expected_min,
        "expected_max": effect.expected_max,
        "confidence": effect.confidence,
    }


def _direction(effect: ObjectiveEffect, baseline: ObjectiveEffect | None) -> str:
    if baseline is None:
        return "unknown"
    midpoint = (effect.expected_min + effect.expected_max) / 2
    baseline_midpoint = (baseline.expected_min + baseline.expected_max) / 2
    if midpoint > baseline_midpoint:
        return "increase"
    if midpoint < baseline_midpoint:
        return "decrease"
    return "hold"


def _lineage_id(kind: str, *parts: str) -> str:
    from fdai.core.ontology_platform.functions import ontology_function_digest

    digest = ontology_function_digest({"kind": kind, "parts": list(parts)})
    return f"{kind}:{digest.removeprefix('sha256:')}"


__all__ = [
    "OperationalPlanningProspectiveFinalizer",
    "StateStoreProspectiveLineageReadinessReader",
    "StateStoreProspectiveLineageMaterializer",
    "build_prospective_lineage_records",
]
