from __future__ import annotations

import pytest
from scripts.automation.conversation_assurance_question_contract import (
    CHALLENGE_QUESTION_CONTRACTS,
    TypedQuestionContract,
    challenge_question_contract,
    reduce_semantic_equivalence,
    wording_proposal,
)


@pytest.fixture
def subscription_health_contract() -> TypedQuestionContract:
    return TypedQuestionContract(
        intent="query.subscription_service_health",
        scope_kind="configured_subscription",
        target_cardinality="scope_aggregate",
        required_authority="server_subscription_health",
        required_capability=("query.subscription_service_health",),
        result_shape="service_health_summary",
        allowed_evidence_posture=("authoritative_current", "explicit_unknown"),
    )


def _review_payload(
    contract: TypedQuestionContract,
    *,
    locale: str = "en",
    **contract_changes: object,
) -> dict[str, object]:
    observed = contract.to_dict()
    observed.update(contract_changes)
    return {
        "equivalent": True,
        "same_language": True,
        "locale": locale,
        "confidence": 0.96,
        "observed_contract": observed,
    }


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("scope_kind", "exact_resource"),
        ("target_cardinality", "single"),
        ("required_authority", "server_inventory_graph"),
        ("result_shape", "resource_detail"),
        ("interaction_target", "named_agent"),
        ("time_window", "historical"),
        ("required_facets", ["resource_id"]),
    ],
)
def test_semantic_equivalence_rejects_meaning_changes(
    subscription_health_contract: TypedQuestionContract,
    field: str,
    changed_value: object,
) -> None:
    decision = reduce_semantic_equivalence(
        _review_payload(subscription_health_contract, **{field: changed_value}),
        expected=subscription_health_contract,
        expected_locale="en",
    )

    assert not decision.accepted
    assert decision.changed_fields == (field,)
    assert decision.reason == "typed_contract_changed"


def test_semantic_equivalence_preserves_contract_across_english_and_korean(
    subscription_health_contract: TypedQuestionContract,
) -> None:
    english = reduce_semantic_equivalence(
        _review_payload(subscription_health_contract, locale="en"),
        expected=subscription_health_contract,
        expected_locale="en",
    )
    korean = reduce_semantic_equivalence(
        _review_payload(subscription_health_contract, locale="ko"),
        expected=subscription_health_contract,
        expected_locale="ko",
    )

    assert english.accepted
    assert korean.accepted
    assert english.changed_fields == korean.changed_fields == ()


def test_generation_output_cannot_replace_typed_contract() -> None:
    payload = {
        "question": "Are there current service-health outages in this subscription?",
        "locale": "en",
        "challenge_id": "service-outage",
        "scope_kind": "exact_resource",
    }

    assert wording_proposal(payload, challenge_id="service-outage", locale="en") is None


def test_generation_output_accepts_wording_only() -> None:
    payload = {
        "question": "  Are there current service-health outages in this subscription?  ",
        "locale": "en",
        "challenge_id": "service-outage",
    }

    assert (
        wording_proposal(
            payload,
            challenge_id="service-outage",
            locale="en",
        )
        == "Are there current service-health outages in this subscription?"
    )


def test_every_assurance_challenge_has_an_immutable_typed_contract() -> None:
    assert set(CHALLENGE_QUESTION_CONTRACTS) == {
        "approval-execution-separation",
        "bragi-translator-boundary",
        "change-rollback-readiness",
        "chaos-stop-recovery",
        "dr-rto-rpo-evidence",
        "insufficient-evidence",
        "llm-usage-trend-chart",
        "ontology-action-count",
        "pantheon-count",
        "resource-health-timeline",
        "resource-state",
        "running-vm-filter",
        "safe-autonomy-invariants",
        "service-outage",
        "shadow-mode",
        "t2-quality-gate",
        "thor-forseti-boundary",
    }
    assert all(
        contract.intent
        and contract.scope_kind
        and contract.target_cardinality
        and contract.required_authority
        and contract.required_capability
        and contract.result_shape
        and contract.allowed_evidence_posture
        for contract in CHALLENGE_QUESTION_CONTRACTS.values()
    )


def test_regression_challenge_contracts_preserve_scope_and_cardinality() -> None:
    subscription_health = challenge_question_contract("service-outage")
    running_vms = challenge_question_contract("running-vm-filter")

    assert subscription_health.intent == "query.subscription_service_health"
    assert subscription_health.scope_kind == "configured_subscription"
    assert subscription_health.target_cardinality == "scope_aggregate"
    assert subscription_health.result_shape == "service_health_summary"
    assert running_vms.scope_kind == "configured_subscription"
    assert running_vms.target_cardinality == "collection"
    assert running_vms.result_shape == "resource_state_table"
