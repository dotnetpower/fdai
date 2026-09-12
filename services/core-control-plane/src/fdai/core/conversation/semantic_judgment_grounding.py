"""Validate and normalize source-grounded semantic judgment candidates."""

from __future__ import annotations

import logging
from typing import Any

from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentProposal,
    SemanticTarget,
)

_LOGGER = logging.getLogger(__name__)


def ground_unique_source_spans(
    proposal: SemanticJudgmentProposal,
    *,
    utterance: str,
    capabilities: tuple[dict[str, Any], ...],
    allow_context_target_drop: bool = True,
) -> SemanticJudgmentProposal:
    """Correct only a unique exact current-turn value and retain legacy context omission."""

    canonical_targets = {
        (kind, name)
        for capability in capabilities
        if isinstance((kind := capability.get("kind")), str)
        if isinstance((name := capability.get("name")), str)
    }
    changed = False
    grounded_fields: dict[str, tuple[SemanticTarget, ...]] = {}
    for field_name, proposed_targets in (
        ("targets", proposal.targets),
        ("forbidden_actions", proposal.forbidden_actions),
    ):
        grounded_targets: list[SemanticTarget] = []
        for target_index, target in enumerate(proposed_targets):
            if utterance[target.source_start : target.source_end] == target.value:
                grounded_targets.append(target)
                continue
            source_start = utterance.find(target.value)
            second_start = (
                utterance.find(target.value, source_start + 1) if source_start >= 0 else -1
            )
            if source_start < 0 or second_start >= 0:
                _LOGGER.warning(
                    "semantic_judgment_target_span_unresolved",
                    extra={
                        "target_field": field_name,
                        "target_index": target_index,
                        "target_kind": target.kind,
                        "exact_occurrences": 0 if source_start < 0 else 2,
                    },
                )
                if (
                    allow_context_target_drop
                    and field_name == "targets"
                    and target.canonical_value is not None
                    and (target.kind, target.canonical_value) in canonical_targets
                ):
                    changed = True
                    continue
                grounded_targets.append(target)
                continue
            grounded_targets.append(
                target.model_copy(
                    update={
                        "source_start": source_start,
                        "source_end": source_start + len(target.value),
                    }
                )
            )
            changed = True
        grounded_fields[field_name] = tuple(grounded_targets)
    return proposal.model_copy(update=grounded_fields) if changed else proposal


def normalize_action_advice_identity_ambiguity(
    proposal: SemanticJudgmentProposal,
) -> SemanticJudgmentProposal:
    if (
        proposal.primary_intent != "action_requirements"
        or proposal.action_posture != "advise_only"
        or not any(target.kind == "resource_type" for target in proposal.targets)
        or not proposal.ambiguous
        or not _alternatives_repeat_primary(proposal)
        or proposal.unresolved_terms != ("resource_identity",)
    ):
        return proposal
    return _without_ambiguity(proposal)


def normalize_exact_resource_identity_ambiguity(
    proposal: SemanticJudgmentProposal,
) -> SemanticJudgmentProposal:
    """Remove only ambiguity contradicted by one typed exact Resource target."""

    exact_resources = tuple(target for target in proposal.targets if target.kind == "resource")
    if (
        proposal.primary_intent != "query.resource_current_state"
        or len(exact_resources) != 1
        or not proposal.ambiguous
        or not _alternatives_repeat_primary(proposal)
        or proposal.unresolved_terms != ("resource_identity",)
    ):
        return proposal
    return _without_ambiguity(proposal)


def normalize_complete_target_ambiguity(
    proposal: SemanticJudgmentProposal,
) -> SemanticJudgmentProposal:
    """Remove ambiguity contradicted by complete typed server-scope or draft targets."""

    if not proposal.ambiguous or proposal.action_posture not in {"advise_only", "draft_only"}:
        return proposal
    facets = set(proposal.requested_facets)
    kinds = {target.kind for target in proposal.targets}
    subscription_complete = (
        proposal.primary_intent == "query.subscription_service_health"
        and not proposal.targets
        and {"current_state", "subscription"}.intersection(facets)
    )
    resource_health_history_complete = (
        proposal.primary_intent == "query.resource_event_history"
        and "time_range" in kinds
        and not {"resource", "resource_group"}.intersection(kinds)
    )
    compound_resource_collection_complete = (
        proposal.primary_intent == "query.subscription_service_health"
        and "query.resource_state_inventory" in proposal.secondary_intents
        and "resource_type" in kinds
        and not {"resource", "resource_group"}.intersection(kinds)
    )
    error_correlation_complete = (
        proposal.primary_intent == "query.resource_error_activity_correlation"
        and {"resource", "time_range"} <= kinds
        and proposal.action_posture == "advise_only"
    )
    incident_create_complete = (
        proposal.primary_intent == "action_request"
        and proposal.action_subject == "Incident"
        and "incident_create" in facets
        and {"resource", "severity"} <= kinds
    )
    return (
        _without_ambiguity(proposal)
        if (
            subscription_complete
            or resource_health_history_complete
            or compound_resource_collection_complete
            or error_correlation_complete
            or incident_create_complete
        )
        else proposal
    )


def normalize_intents_from_typed_facets(
    proposal: SemanticJudgmentProposal,
    *,
    capabilities: tuple[dict[str, Any], ...],
) -> SemanticJudgmentProposal:
    """Complete procedure intent only from proposed facets and supplied intent names."""

    intent_names = {
        name
        for capability in capabilities
        if capability.get("kind") in {"intent", "question_domain"}
        if isinstance((name := capability.get("name")), str)
    }
    if "action_requirements" not in intent_names or not {
        "delete",
        "deletion",
        "procedure",
    }.intersection(proposal.requested_facets):
        return proposal
    primary_intent = (
        "action_requirements"
        if proposal.primary_intent == "explanation"
        else proposal.primary_intent
    )
    secondary_intents = tuple(
        "action_requirements" if intent == "explanation" else intent
        for intent in proposal.secondary_intents
    )
    if primary_intent.startswith("query.") and "action_requirements" not in secondary_intents:
        secondary_intents = (*secondary_intents, "action_requirements")
    if (
        primary_intent == proposal.primary_intent
        and secondary_intents == proposal.secondary_intents
    ):
        return proposal
    return proposal.model_copy(
        update={
            "primary_intent": primary_intent,
            "secondary_intents": secondary_intents,
        }
    )


def normalize_required_identity_clarification(
    proposal: SemanticJudgmentProposal,
    *,
    locale: str,
) -> SemanticJudgmentProposal:
    """Complete fail-closed identity clarification from a typed subtype-only request."""

    kinds = {target.kind for target in proposal.targets}
    subtype_only_current_state = (
        proposal.primary_intent == "query.resource_current_state"
        and "resource_type" in kinds
        and "resource" not in kinds
    )
    subtype_only_action = (
        proposal.primary_intent == "action_request"
        and proposal.action_posture == "draft_only"
        and proposal.action_subject == "ActionType"
        and "resource_type" in kinds
        and not {"action_type", "resource"}.intersection(kinds)
    )
    if proposal.ambiguous or not (subtype_only_current_state or subtype_only_action):
        return proposal
    clarification = (
        "어떤 리소스의 정확한 이름이나 ID를 사용할까요?"
        if locale == "ko"
        else "Which exact resource name or ID should I use?"
    )
    return proposal.model_copy(
        update={
            "ambiguous": True,
            "alternatives": (),
            "unresolved_terms": ("resource_identity",),
            "clarification": clarification,
        }
    )


def normalize_incident_mitigation_identity_clarification(
    proposal: SemanticJudgmentProposal,
    *,
    bound_incident: bool,
    locale: str,
) -> SemanticJudgmentProposal:
    """Require one incident identity before an unbound mitigation draft."""

    if (
        bound_incident
        or proposal.primary_intent != "action_request"
        or proposal.action_posture != "draft_only"
        or proposal.action_subject != "Incident"
        or "incident_mitigation" not in proposal.requested_facets
        or any(target.kind == "incident_id" for target in proposal.targets)
    ):
        return proposal
    clarification = (
        "완화 초안에 사용할 정확한 장애 ID는 무엇인가요?"
        if locale == "ko"
        else "Which exact incident ID should the mitigation draft use?"
    )
    return proposal.model_copy(
        update={
            "ambiguous": True,
            "alternatives": (),
            "unresolved_terms": ("incident_identity",),
            "clarification": clarification,
        }
    )


def normalize_overlapping_target_fragments(
    proposal: SemanticJudgmentProposal,
) -> SemanticJudgmentProposal:
    """Drop subtype fragments that occupy only part of one exact Resource target."""

    exact_resources = tuple(target for target in proposal.targets if target.kind == "resource")
    if len(exact_resources) != 1:
        return proposal
    resource = exact_resources[0]
    targets = tuple(
        target
        for target in proposal.targets
        if not (
            target.kind == "resource_type"
            and resource.source_start <= target.source_start
            and target.source_end <= resource.source_end
            and (target.source_start, target.source_end)
            != (resource.source_start, resource.source_end)
        )
    )
    return (
        proposal
        if targets == proposal.targets
        else proposal.model_copy(update={"targets": targets})
    )


def normalize_schema_object_type_suffix(
    proposal: SemanticJudgmentProposal,
) -> SemanticJudgmentProposal:
    """Remove generic metatype wording from supplied schema subjects."""

    if proposal.primary_intent not in {
        "query.ontology_declaration",
        "query.ontology_relationships",
    }:
        return proposal
    targets = tuple(
        (
            target.model_copy(
                update={
                    "value": target.canonical_value,
                    "source_end": target.source_start + len(target.canonical_value),
                }
            )
            if target.kind == "object_type"
            and target.canonical_value is not None
            and target.value == f"{target.canonical_value} ObjectType"
            else target
        )
        for target in proposal.targets
    )
    metatype_targets = {"LinkType", "ObjectType"}
    if any(
        target.kind == "object_type" and target.canonical_value not in metatype_targets
        for target in targets
    ):
        targets = tuple(
            target
            for target in targets
            if not (target.kind == "object_type" and target.canonical_value in metatype_targets)
        )
    return (
        proposal
        if targets == proposal.targets
        else proposal.model_copy(update={"targets": targets})
    )


def recover_unique_schema_subject(
    proposal: SemanticJudgmentProposal,
    *,
    utterance: str,
    capabilities: tuple[dict[str, Any], ...],
) -> SemanticJudgmentProposal:
    """Ground one missing schema subject from an exact supplied current-turn identity."""

    if proposal.primary_intent not in {
        "query.ontology_declaration",
        "query.ontology_relationships",
    }:
        return proposal
    metatypes = {"LinkType", "ObjectType"}
    concrete_targets = {
        target.canonical_value
        for target in proposal.targets
        if target.kind == "object_type"
        and target.canonical_value is not None
        and target.canonical_value not in metatypes
    }
    if concrete_targets:
        return proposal
    supplied = {
        name
        for capability in capabilities
        if capability.get("kind") == "object_type"
        if isinstance((name := capability.get("name")), str) and name not in metatypes
    }
    matches = tuple(
        (name, start)
        for name in supplied
        if (start := _unique_bounded_occurrence(utterance, name)) is not None
    )
    if len(matches) != 1:
        return proposal
    name, source_start = matches[0]
    retained = tuple(
        target
        for target in proposal.targets
        if not (target.kind == "object_type" and target.canonical_value in metatypes)
    )
    target = SemanticTarget(
        kind="object_type",
        value=name,
        canonical_value=name,
        source_start=source_start,
        source_end=source_start + len(name),
    )
    return proposal.model_copy(update={"targets": (*retained, target)})


def _unique_bounded_occurrence(utterance: str, value: str) -> int | None:
    source_start = utterance.find(value)
    if source_start < 0 or utterance.find(value, source_start + 1) >= 0:
        return None
    source_end = source_start + len(value)
    if source_start > 0 and utterance[source_start - 1].isalnum():
        return None
    if source_end < len(utterance) and utterance[source_end].isalnum():
        return None
    return source_start


def normalize_target_shape(proposal: SemanticJudgmentProposal) -> SemanticJudgmentProposal:
    """Keep only target roles licensed by the proposed typed intent family."""

    targets = proposal.targets
    allowed: set[str] | None = None
    facets = set(proposal.requested_facets)
    if proposal.primary_intent == "query.resource_error_activity_correlation":
        allowed = {"resource", "time_range"}
    elif proposal.primary_intent in {
        "query.resource_change_activity",
        "query.resource_current_state",
    }:
        allowed = {"resource", "resource_type"}
    elif proposal.primary_intent == "query.resource_event_history":
        allowed = {"event_type", "resource", "resource_type", "time_range"}
    elif proposal.primary_intent == "query.subscription_service_health":
        allowed = (
            {"resource_type"}
            if "query.resource_state_inventory" in proposal.secondary_intents
            else set()
        )
    elif proposal.primary_intent == "query.incident_evidence":
        allowed = {"incident_id"}
    elif proposal.primary_intent == "query.contextual_resources":
        allowed = {"resource_group", "resource_type"}
    elif proposal.primary_intent == "action_requirements":
        allowed = {"action_type", "object_type", "resource_type"}
    elif proposal.primary_intent == "action_request" and proposal.action_subject == "ActionType":
        allowed = {"action_type", "resource", "resource_type"}
    elif proposal.primary_intent == "action_request" and proposal.action_subject == "Incident":
        if "incident_create" in facets and len(targets) >= 2:
            ordered = sorted(targets, key=lambda target: (target.source_start, target.source_end))
            targets = (
                ordered[0].model_copy(update={"kind": "severity", "canonical_value": None}),
                ordered[-1].model_copy(update={"kind": "resource", "canonical_value": None}),
            )
        allowed = {"resource", "severity"} if "incident_create" in facets else {"incident_id"}
    elif proposal.primary_intent == "explanation" and proposal.discourse_mode.value == "quoted":
        allowed = set()
    if allowed is None:
        return proposal
    selected = [target for target in targets if target.kind in allowed]
    if any(target.kind == "resource_type" for target in selected) and not any(
        target.kind == "resource" for target in selected
    ):
        selected = [target for target in selected if target.kind != "action_type"]
    if any(target.kind == "resource" for target in selected):
        selected = [target for target in selected if target.kind != "resource_type"]
    targets = tuple(
        sorted(
            dict.fromkeys(selected),
            key=lambda target: (
                target.source_start,
                target.source_end,
                target.kind,
                target.value,
            ),
        )
    )
    return (
        proposal
        if targets == proposal.targets
        else proposal.model_copy(update={"targets": targets})
    )


def normalize_unsupplied_time_canonical_values(
    proposal: SemanticJudgmentProposal,
    *,
    capabilities: tuple[dict[str, Any], ...],
) -> SemanticJudgmentProposal:
    supplied = {
        value
        for capability in capabilities
        for field in ("measure_concepts", "canonical_values")
        if isinstance((values := capability.get(field)), (list, tuple))
        for value in values
        if isinstance(value, str)
    }
    targets = tuple(
        (
            target.model_copy(update={"canonical_value": None})
            if target.kind == "time_range"
            and target.canonical_value is not None
            and target.canonical_value not in supplied
            else target
        )
        for target in proposal.targets
    )
    return (
        proposal
        if targets == proposal.targets
        else proposal.model_copy(update={"targets": targets})
    )


def validate_action_target_ambiguity(proposal: SemanticJudgmentProposal) -> None:
    if (
        proposal.action_posture == "draft_only"
        and proposal.action_subject == "ActionType"
        and not proposal.ambiguous
        and not any(target.kind in {"action_type", "resource"} for target in proposal.targets)
    ):
        raise ValueError("semantic draft action requires an exact target or clarification")


def validate_required_target_shape(proposal: SemanticJudgmentProposal) -> None:
    """Require targets implied by the already proposed typed intent and facets."""

    kinds = {target.kind for target in proposal.targets}
    facets = set(proposal.requested_facets)
    if proposal.primary_intent == "query.resource_current_state":
        if "resource" not in kinds and not ("resource_type" in kinds and proposal.ambiguous):
            raise ValueError(
                "semantic current-state intent requires exact Resource or clarification"
            )
    elif (
        proposal.primary_intent == "query.resource_change_activity"
        and "resource" not in kinds
        and not _targetless_resource_change_collection(proposal)
    ):
        raise ValueError("semantic Resource activity intent requires exact Resource")
    elif (
        proposal.primary_intent == "query.resource_error_activity_correlation"
        and not {
            "resource",
            "time_range",
        }
        <= kinds
    ):
        raise ValueError("semantic error correlation requires Resource and time range")
    elif (
        proposal.primary_intent == "query.resource_event_history"
        and "time_range" in facets
        and "time_range" not in kinds
    ):
        raise ValueError("semantic event history requires its requested time range")
    elif proposal.primary_intent == "query.incident_evidence" and "incident_id" not in kinds:
        raise ValueError("semantic incident evidence requires incident id")
    elif (
        proposal.primary_intent == "query.contextual_resources"
        and {"current_state", "name_filter"} <= facets
        and not {"resource_group", "resource_type"} <= kinds
    ):
        raise ValueError("semantic contextual state list requires group and resource type")
    elif (
        proposal.primary_intent == "query.subscription_service_health"
        and "query.resource_state_inventory" in proposal.secondary_intents
        and "resource_type" not in kinds
    ):
        raise ValueError("semantic compound state intent requires resource type")
    elif (
        proposal.primary_intent == "action_requirements"
        and not {"action_type", "resource_type"}.intersection(kinds)
        and not (
            "incident_mitigation" in facets
            and any(
                target.kind == "object_type" and target.canonical_value == "Incident"
                for target in proposal.targets
            )
        )
    ):
        raise ValueError("semantic action requirements require action or resource type")
    elif (
        proposal.primary_intent == "action_request"
        and proposal.action_subject == "Incident"
        and "incident_create" in facets
        and not {"resource", "severity"} <= kinds
    ):
        raise ValueError("semantic incident creation requires severity and Resource")
    elif (
        proposal.primary_intent == "action_request"
        and proposal.action_subject == "Incident"
        and "incident_mitigation" in facets
        and "incident_id" not in kinds
        and not (proposal.ambiguous and proposal.unresolved_terms == ("incident_identity",))
    ):
        raise ValueError("semantic incident mitigation requires incident id")


def validate_capability_grounding(
    proposal: SemanticJudgmentProposal,
    *,
    capabilities: tuple[dict[str, Any], ...],
) -> None:
    allowed_intents: set[str] = set()
    allowed_canonical_values: set[str] = set()
    names_by_kind: dict[str, set[str]] = {}
    for capability in capabilities:
        kind = capability.get("kind")
        name = capability.get("name")
        if isinstance(name, str):
            allowed_canonical_values.add(name)
            if isinstance(kind, str):
                names_by_kind.setdefault(kind, set()).add(name)
            if kind in {"action_type", "function_type", "intent", "question_domain"}:
                allowed_intents.add(name)
            if kind == "link_type":
                allowed_intents.add(f"query.{name}")
        intent = capability.get("intent")
        if isinstance(intent, str):
            allowed_intents.add(intent)
        for field in ("question_domains", "measure_concepts", "canonical_values"):
            values = capability.get(field)
            if isinstance(values, (list, tuple)) and all(
                isinstance(value, str) for value in values
            ):
                allowed_canonical_values.update(values)
                if field == "question_domains":
                    allowed_intents.update(values)
    if any(
        intent not in allowed_intents
        for intent in (proposal.primary_intent, *proposal.secondary_intents)
    ):
        raise ValueError("semantic intent is not supplied by capabilities")
    if any(
        target.canonical_value is not None
        and target.canonical_value not in allowed_canonical_values
        for target in (*proposal.targets, *proposal.forbidden_actions)
    ):
        raise ValueError("semantic target canonical identity is not supplied")
    capability_kind_by_target = {
        "action_type": "action_type",
        "object_type": "object_type",
        "resource_type": "resource_type",
    }
    instance_kinds = {"incident_id", "resource", "resource_group", "severity", "time_range"}
    for target in proposal.targets:
        canonical_value = target.canonical_value
        if canonical_value is None:
            continue
        if target.kind in instance_kinds:
            raise ValueError("semantic instance target MUST NOT carry a catalog type identity")
        capability_kind = capability_kind_by_target.get(target.kind)
        if capability_kind is not None and canonical_value not in names_by_kind.get(
            capability_kind, set()
        ):
            raise ValueError("semantic target canonical identity kind does not match")


def validate_forbidden_action_canonical_values(
    proposal: SemanticJudgmentProposal,
    *,
    capabilities: tuple[dict[str, Any], ...],
) -> None:
    supplied = {
        (kind, name)
        for capability in capabilities
        if isinstance((kind := capability.get("kind")), str)
        if isinstance((name := capability.get("name")), str)
    }
    if any(
        action.canonical_value is not None and (action.kind, action.canonical_value) not in supplied
        for action in proposal.forbidden_actions
    ):
        raise ValueError("semantic forbidden action canonical identity is not supplied")


def validate_source_spans(proposal: SemanticJudgmentProposal, *, utterance: str) -> None:
    for field, targets in (
        ("target", proposal.targets),
        ("forbidden action", proposal.forbidden_actions),
    ):
        for target in targets:
            if target.source_end > len(utterance):
                raise ValueError(f"semantic {field} source span exceeds the utterance")
            if utterance[target.source_start : target.source_end] != target.value:
                raise ValueError(f"semantic {field} source span does not match the utterance")


def _without_ambiguity(proposal: SemanticJudgmentProposal) -> SemanticJudgmentProposal:
    return proposal.model_copy(
        update={
            "ambiguous": False,
            "unresolved_terms": (),
            "clarification": None,
        }
    )


def _alternatives_repeat_primary(proposal: SemanticJudgmentProposal) -> bool:
    return not proposal.alternatives or set(proposal.alternatives) == {proposal.primary_intent}


def _targetless_resource_change_collection(proposal: SemanticJudgmentProposal) -> bool:
    if proposal.targets or proposal.secondary_intents or proposal.action_subject != "none":
        return False
    facets = {facet.replace("-", "_") for facet in proposal.requested_facets}
    return bool(
        facets.intersection(
            {
                "changed_resources",
                "recent_resource_changes",
                "recent_state_changes",
                "recently_changed",
                "resource_changes",
                "state_changes",
            }
        )
    )


__all__ = [
    "ground_unique_source_spans",
    "normalize_action_advice_identity_ambiguity",
    "normalize_complete_target_ambiguity",
    "normalize_exact_resource_identity_ambiguity",
    "normalize_intents_from_typed_facets",
    "normalize_overlapping_target_fragments",
    "normalize_required_identity_clarification",
    "normalize_schema_object_type_suffix",
    "recover_unique_schema_subject",
    "normalize_target_shape",
    "normalize_unsupplied_time_canonical_values",
    "validate_action_target_ambiguity",
    "validate_capability_grounding",
    "validate_forbidden_action_canonical_values",
    "validate_required_target_shape",
    "validate_source_spans",
]
