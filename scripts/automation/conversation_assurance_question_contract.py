"""Typed question contracts for the local conversation-assurance generator."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

_CONTRACT_FIELDS = (
    "intent",
    "scope_kind",
    "target_cardinality",
    "required_authority",
    "required_capability",
    "result_shape",
    "allowed_evidence_posture",
    "interaction_target",
    "time_window",
    "required_facets",
)


@dataclass(frozen=True, slots=True)
class TypedQuestionContract:
    """Immutable meaning that generated wording must preserve."""

    intent: str
    scope_kind: str
    target_cardinality: str
    required_authority: str
    required_capability: tuple[str, ...]
    result_shape: str
    allowed_evidence_posture: tuple[str, ...]
    interaction_target: str = "operator_read_surface"
    time_window: str = "not_applicable"
    required_facets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        scalar_values = (
            self.intent,
            self.scope_kind,
            self.target_cardinality,
            self.required_authority,
            self.result_shape,
            self.interaction_target,
            self.time_window,
        )
        if any(not value.strip() for value in scalar_values):
            raise ValueError("typed question contract fields MUST be non-empty")
        if any(not value.strip() for value in self.required_capability):
            raise ValueError("required capabilities MUST be non-empty")
        if not self.allowed_evidence_posture or any(
            not value.strip() for value in self.allowed_evidence_posture
        ):
            raise ValueError("allowed evidence posture MUST be non-empty")
        if any(not value.strip() for value in self.required_facets):
            raise ValueError("required facets MUST be non-empty")

    def to_dict(self) -> dict[str, object]:
        """Return the canonical machine contract used by generation and review."""

        return {
            "intent": self.intent,
            "scope_kind": self.scope_kind,
            "target_cardinality": self.target_cardinality,
            "required_authority": self.required_authority,
            "required_capability": list(self.required_capability),
            "result_shape": self.result_shape,
            "allowed_evidence_posture": list(self.allowed_evidence_posture),
            "interaction_target": self.interaction_target,
            "time_window": self.time_window,
            "required_facets": list(self.required_facets),
        }


CHALLENGE_QUESTION_CONTRACTS: Mapping[str, TypedQuestionContract] = MappingProxyType(
    {
        "thor-forseti-boundary": TypedQuestionContract(
            intent="explain.agent_authority_boundary",
            scope_kind="framework_contract",
            target_cardinality="role_pair",
            required_authority="repository_constitution",
            required_capability=("query.agent_role_contract",),
            result_shape="explanation",
            allowed_evidence_posture=("repository_grounded", "explicit_unknown"),
        ),
        "bragi-translator-boundary": TypedQuestionContract(
            intent="explain.narration_authority_boundary",
            scope_kind="framework_contract",
            target_cardinality="single_role",
            required_authority="repository_constitution",
            required_capability=("query.agent_role_contract",),
            result_shape="explanation",
            allowed_evidence_posture=("repository_grounded", "explicit_unknown"),
        ),
        "safe-autonomy-invariants": TypedQuestionContract(
            intent="explain.safe_autonomy_safeguards",
            scope_kind="framework_contract",
            target_cardinality="safeguard_set",
            required_authority="repository_constitution",
            required_capability=("query.safe_autonomy_contract",),
            result_shape="complete_list",
            allowed_evidence_posture=("repository_grounded", "explicit_unknown"),
        ),
        "approval-execution-separation": TypedQuestionContract(
            intent="explain.approval_execution_separation",
            scope_kind="framework_contract",
            target_cardinality="role_pair",
            required_authority="repository_constitution",
            required_capability=("query.agent_role_contract",),
            result_shape="explanation",
            allowed_evidence_posture=("repository_grounded", "explicit_unknown"),
        ),
        "shadow-mode": TypedQuestionContract(
            intent="explain.shadow_mode",
            scope_kind="framework_contract",
            target_cardinality="single_capability",
            required_authority="repository_constitution",
            required_capability=("query.autonomy_mode_contract",),
            result_shape="explanation",
            allowed_evidence_posture=("repository_grounded", "explicit_unknown"),
        ),
        "t2-quality-gate": TypedQuestionContract(
            intent="explain.t2_quality_gate",
            scope_kind="framework_contract",
            target_cardinality="gate_set",
            required_authority="repository_constitution",
            required_capability=("query.t2_quality_contract",),
            result_shape="complete_list",
            allowed_evidence_posture=("repository_grounded", "explicit_unknown"),
        ),
        "insufficient-evidence": TypedQuestionContract(
            intent="explain.insufficient_evidence_behavior",
            scope_kind="framework_contract",
            target_cardinality="single_decision",
            required_authority="repository_constitution",
            required_capability=("query.evidence_behavior_contract",),
            result_shape="explanation",
            allowed_evidence_posture=("repository_grounded", "explicit_unknown"),
        ),
        "pantheon-count": TypedQuestionContract(
            intent="query.pantheon_count",
            scope_kind="active_pantheon",
            target_cardinality="set_aggregate",
            required_authority="server_pantheon_manifest",
            required_capability=("query.pantheon_manifest",),
            result_shape="count_with_examples",
            allowed_evidence_posture=("authoritative_current", "explicit_unknown"),
            interaction_target="server_owned_read_surface",
            time_window="current",
            required_facets=("example_count:2",),
        ),
        "ontology-action-count": TypedQuestionContract(
            intent="query.ontology_action_type_count",
            scope_kind="active_ontology_release",
            target_cardinality="set_aggregate",
            required_authority="server_ontology_manifest",
            required_capability=("query.manifest",),
            result_shape="scalar_count",
            allowed_evidence_posture=("authoritative_current", "explicit_unknown"),
            interaction_target="server_owned_read_surface",
            time_window="current",
        ),
        "service-outage": TypedQuestionContract(
            intent="query.subscription_service_health",
            scope_kind="configured_subscription",
            target_cardinality="scope_aggregate",
            required_authority="server_subscription_health",
            required_capability=("query.subscription_service_health",),
            result_shape="service_health_summary",
            allowed_evidence_posture=("authoritative_current", "explicit_unknown"),
            interaction_target="server_owned_read_surface",
            time_window="current",
            required_facets=("outage_status",),
        ),
        "resource-state": TypedQuestionContract(
            intent="query.resource_condition_collection",
            scope_kind="configured_subscription",
            target_cardinality="collection",
            required_authority="server_subscription_health",
            required_capability=("query.subscription_service_health",),
            result_shape="condition_grouped_collection",
            allowed_evidence_posture=("authoritative_current", "explicit_unknown"),
            interaction_target="server_owned_read_surface",
            time_window="current",
            required_facets=(
                "condition:stopped",
                "condition:deallocated",
                "condition:failed",
                "condition:degraded",
                "condition:unavailable",
            ),
        ),
        "running-vm-filter": TypedQuestionContract(
            intent="query.running_virtual_machine_collection",
            scope_kind="configured_subscription",
            target_cardinality="collection",
            required_authority="server_inventory_graph",
            required_capability=("query.resource_state_inventory",),
            result_shape="resource_state_table",
            allowed_evidence_posture=("authoritative_current", "explicit_unknown"),
            interaction_target="server_owned_read_surface",
            time_window="current",
            required_facets=("resource_type:virtual_machine", "power_state:running"),
        ),
        "resource-health-timeline": TypedQuestionContract(
            intent="query.resource_health_timeline_collection",
            scope_kind="configured_subscription",
            target_cardinality="collection",
            required_authority="server_subscription_health",
            required_capability=("query.resource_health_inventory",),
            result_shape="resource_health_timeline",
            allowed_evidence_posture=("authoritative_current", "explicit_unknown"),
            interaction_target="server_owned_read_surface",
            time_window="current",
            required_facets=("observed_time", "cause_class"),
        ),
        "llm-usage-trend-chart": TypedQuestionContract(
            intent="query.chat_token_usage_timeseries",
            scope_kind="configured_subscription",
            target_cardinality="time_series",
            required_authority="server_metering",
            required_capability=("query.chat_token_usage",),
            result_shape="time_series_chart",
            allowed_evidence_posture=("authoritative_current", "explicit_unknown"),
            interaction_target="server_owned_read_surface",
            time_window="last_7_days",
            required_facets=("daily_token_usage",),
        ),
        "change-rollback-readiness": TypedQuestionContract(
            intent="explain.rollback_readiness",
            scope_kind="proposed_change",
            target_cardinality="single_change",
            required_authority="server_change_evidence",
            required_capability=("query.change_readiness",),
            result_shape="evidence_explanation",
            allowed_evidence_posture=("authoritative_current", "explicit_unknown"),
        ),
        "dr-rto-rpo-evidence": TypedQuestionContract(
            intent="query.recovery_objective_evidence",
            scope_kind="completed_recovery",
            target_cardinality="single_recovery",
            required_authority="server_recovery_evidence",
            required_capability=("query.recovery_objectives",),
            result_shape="rto_rpo_evidence",
            allowed_evidence_posture=("authoritative_current", "explicit_unknown"),
        ),
        "chaos-stop-recovery": TypedQuestionContract(
            intent="query.chaos_stop_and_recovery_evidence",
            scope_kind="chaos_experiment",
            target_cardinality="single_experiment",
            required_authority="server_chaos_evidence",
            required_capability=("query.chaos_experiment",),
            result_shape="safety_evidence_explanation",
            allowed_evidence_posture=("authoritative_current", "explicit_unknown"),
        ),
    }
)


def challenge_question_contract(challenge_id: str) -> TypedQuestionContract:
    """Return the immutable contract for one registered assurance challenge."""

    try:
        return CHALLENGE_QUESTION_CONTRACTS[challenge_id]
    except KeyError as exc:
        raise ValueError(f"unknown conversation-assurance challenge: {challenge_id}") from exc


@dataclass(frozen=True, slots=True)
class SemanticEquivalenceDecision:
    """Deterministic reduction of one independent semantic review."""

    accepted: bool
    confidence: float
    changed_fields: tuple[str, ...]
    reason: str


def generation_prompt(
    *,
    challenge_id: str,
    objective: str,
    contract: TypedQuestionContract,
    prior_questions: tuple[str, ...],
    locale: str,
    max_question_chars: int,
) -> str:
    """Build a wording-only generation request bound to an immutable contract."""

    prior_block = "\n".join(f"- {item[:300]}" for item in prior_questions[-40:]) or "- none"
    return f"""Generate exactly one natural operator question for FDAI.
Return only JSON with this exact schema and no additional fields:
{{"question":"...","locale":"{locale}","challenge_id":"{challenge_id}"}}

Typed question contract (immutable):
{json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True)}

Wording objective:
{objective}

Rules:
- Propose wording only. Do not add, remove, infer, or rewrite any typed contract field.
- The question must be in {"Korean" if locale == "ko" else "English"}.
- Ask for the contract's read-only result without narrowing or broadening its scope or targets.
- Do not copy or closely paraphrase any prior question below.
- Do not include tenant ids, subscription ids, resource names, endpoints, credentials, or examples.
- Keep it under {max_question_chars} characters.

Prior questions:
{prior_block}
"""


def equivalence_prompt(
    *,
    challenge_id: str,
    objective: str,
    contract: TypedQuestionContract,
    candidate: str,
    expected_locale: str | None,
    original: str | None = None,
) -> str:
    """Build an independent semantic review request for generated wording."""

    locale_rule = (
        f"The candidate language must be {expected_locale}."
        if expected_locale is not None
        else "The candidate must use the same language as the original."
    )
    original_block = f"\nOriginal question:\n{original}\n" if original is not None else ""
    return f"""Independently review one generated FDAI operator question.
Derive the candidate's meaning from its wording before comparing it with the expected contract.
Return only JSON with this exact schema:
{{
  "equivalent": true,
  "same_language": true,
  "locale": "en|ko",
  "confidence": 0.0,
  "observed_contract": {{
    "intent": "...",
    "scope_kind": "...",
    "target_cardinality": "...",
    "required_authority": "...",
    "required_capability": ["..."],
    "result_shape": "...",
    "allowed_evidence_posture": ["..."],
    "interaction_target": "...",
    "time_window": "...",
    "required_facets": ["..."]
  }}
}}

Challenge id: {challenge_id}
Wording objective: {objective}
Expected typed contract:
{json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True)}
{original_block}
Candidate question:
{candidate}

Rules:
- {locale_rule}
- Reject any narrower or broader scope, changed target cardinality, changed authority, changed
  capability, changed result shape, changed evidence posture, mutation request, or added subject.
- Do not use keyword overlap, phrase matching, or exact wording as the decision rule.
"""


def reduce_semantic_equivalence(
    payload: Mapping[str, Any],
    *,
    expected: TypedQuestionContract,
    expected_locale: str | None,
    minimum_confidence: float = 0.85,
) -> SemanticEquivalenceDecision:
    """Fail closed unless an independent review exactly preserves the typed contract."""

    confidence_value = payload.get("confidence")
    confidence = float(confidence_value) if isinstance(confidence_value, int | float) else 0.0
    observed = payload.get("observed_contract")
    changed_fields = _changed_contract_fields(observed, expected)
    locale = payload.get("locale")
    language_matches = payload.get("same_language") is True and locale in {"en", "ko"}
    if expected_locale is not None:
        language_matches = language_matches and locale == expected_locale
    accepted = (
        payload.get("equivalent") is True
        and language_matches
        and confidence >= minimum_confidence
        and not changed_fields
    )
    if changed_fields:
        reason = "typed_contract_changed"
    elif not language_matches:
        reason = "language_changed"
    elif confidence < minimum_confidence:
        reason = "semantic_confidence_below_threshold"
    elif payload.get("equivalent") is not True:
        reason = "semantic_equivalence_rejected"
    else:
        reason = "accepted"
    return SemanticEquivalenceDecision(
        accepted=accepted,
        confidence=confidence,
        changed_fields=changed_fields,
        reason=reason,
    )


def wording_proposal(payload: Mapping[str, Any], *, challenge_id: str, locale: str) -> str | None:
    """Accept only the wording-only generation schema."""

    if set(payload) != {"question", "locale", "challenge_id"}:
        return None
    question = payload.get("question")
    if (
        payload.get("challenge_id") != challenge_id
        or payload.get("locale") != locale
        or not isinstance(question, str)
    ):
        return None
    return " ".join(question.split())


def _changed_contract_fields(
    observed: object,
    expected: TypedQuestionContract,
) -> tuple[str, ...]:
    if not isinstance(observed, Mapping):
        return _CONTRACT_FIELDS
    expected_values = expected.to_dict()
    changed: list[str] = []
    for field in _CONTRACT_FIELDS:
        actual = observed.get(field)
        wanted = expected_values[field]
        if field in {
            "required_capability",
            "allowed_evidence_posture",
            "required_facets",
        }:
            if (
                not isinstance(wanted, list)
                or not isinstance(actual, list)
                or any(not isinstance(item, str) for item in actual)
                or set(actual) != set(wanted)
            ):
                changed.append(field)
        elif actual != wanted:
            changed.append(field)
    return tuple(changed)


__all__ = [
    "CHALLENGE_QUESTION_CONTRACTS",
    "SemanticEquivalenceDecision",
    "TypedQuestionContract",
    "challenge_question_contract",
    "equivalence_prompt",
    "generation_prompt",
    "reduce_semantic_equivalence",
    "wording_proposal",
]
