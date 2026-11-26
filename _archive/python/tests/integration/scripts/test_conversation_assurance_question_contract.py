from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from scripts.automation.conversation_assurance_question_admission import (
    admit_generated_question,
    admit_paraphrase_cohort,
    persist_admitted_questions,
)
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
        "ontology-agent-declaration",
        "ontology-agent-relationships",
        "ontology-approval-declaration",
        "ontology-approval-relationships",
        "ontology-business-service-declaration",
        "ontology-business-service-relationships",
        "ontology-change-declaration",
        "ontology-change-relationships",
        "ontology-decision-declaration",
        "ontology-decision-relationships",
        "ontology-finding-declaration",
        "ontology-function-count",
        "ontology-incident-declaration",
        "ontology-incident-relationships",
        "ontology-interface-count",
        "ontology-link-count",
        "ontology-object-count",
        "ontology-observation-declaration",
        "ontology-observation-relationships",
        "ontology-recovery-plan-declaration",
        "ontology-resource-declaration",
        "ontology-resource-relationships",
        "ontology-rule-declaration",
        "ontology-rule-relationships",
        "ontology-service-objective-declaration",
        "ontology-service-objective-relationships",
        "ontology-workload-declaration",
        "ontology-workload-relationships",
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


def test_sre_ontology_contracts_use_current_manifest_authority() -> None:
    expected_functions = {
        "ontology-action-count": ("query.manifest",),
        "ontology-function-count": ("query.manifest",),
        "ontology-interface-count": ("query.manifest",),
        "ontology-link-count": ("query.manifest",),
        "ontology-object-count": ("query.manifest",),
        "ontology-agent-declaration": ("query.ontology_declaration",),
        "ontology-approval-declaration": ("query.ontology_declaration",),
        "ontology-business-service-declaration": ("query.ontology_declaration",),
        "ontology-change-declaration": ("query.ontology_declaration",),
        "ontology-decision-declaration": ("query.ontology_declaration",),
        "ontology-finding-declaration": ("query.ontology_declaration",),
        "ontology-incident-declaration": ("query.ontology_declaration",),
        "ontology-observation-declaration": ("query.ontology_declaration",),
        "ontology-recovery-plan-declaration": ("query.ontology_declaration",),
        "ontology-resource-declaration": ("query.ontology_declaration",),
        "ontology-rule-declaration": ("query.ontology_declaration",),
        "ontology-service-objective-declaration": ("query.ontology_declaration",),
        "ontology-workload-declaration": ("query.ontology_declaration",),
        "ontology-agent-relationships": ("query.ontology_relationships",),
        "ontology-approval-relationships": ("query.ontology_relationships",),
        "ontology-business-service-relationships": ("query.ontology_relationships",),
        "ontology-change-relationships": ("query.ontology_relationships",),
        "ontology-decision-relationships": ("query.ontology_relationships",),
        "ontology-incident-relationships": ("query.ontology_relationships",),
        "ontology-observation-relationships": ("query.ontology_relationships",),
        "ontology-resource-relationships": ("query.ontology_relationships",),
        "ontology-rule-relationships": ("query.ontology_relationships",),
        "ontology-service-objective-relationships": ("query.ontology_relationships",),
        "ontology-workload-relationships": ("query.ontology_relationships",),
    }

    for challenge_id, functions in expected_functions.items():
        contract = challenge_question_contract(challenge_id)
        assert contract.required_authority == "server_ontology_manifest"
        assert contract.required_capability == functions
        assert contract.scope_kind == "active_ontology_release"
        assert contract.time_window == "current"
        if functions == ("query.manifest",):
            assert contract.intent == "query.manifest"


def test_schema_challenge_subjects_are_declared_object_types() -> None:
    root = Path(__file__).resolve().parents[3]
    declared = {
        str(payload["name"])
        for path in (root / "rule-catalog/vocabulary/object-types").glob("*.yaml")
        if isinstance((payload := yaml.safe_load(path.read_text(encoding="utf-8"))), dict)
        and isinstance(payload.get("name"), str)
    }
    challenged = {
        facet.removeprefix("declaration:")
        for contract in CHALLENGE_QUESTION_CONTRACTS.values()
        for facet in contract.required_facets
        if facet.startswith("declaration:")
    }

    assert challenged <= declared


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


def test_question_admission_retries_semantic_drift_before_accepting(
    subscription_health_contract: TypedQuestionContract,
) -> None:
    proposals = (
        {
            "question": "Which exact resource has a health incident?",
            "locale": "en",
            "challenge_id": "service-outage",
        },
        {
            "question": "Are any service-health outages active in this subscription?",
            "locale": "en",
            "challenge_id": "service-outage",
        },
    )
    reviews = iter(
        (
            _review_payload(
                subscription_health_contract,
                scope_kind="exact_resource",
                target_cardinality="single",
            ),
            _review_payload(subscription_health_contract),
        )
    )

    decision = admit_generated_question(
        challenge_id="service-outage",
        contract=subscription_health_contract,
        locale="en",
        attempts=2,
        propose=lambda attempt: proposals[attempt],
        review=lambda _question: next(reviews),
    )

    assert decision.accepted
    assert decision.attempts == 2
    assert decision.rejection_reasons == ("typed_contract_changed",)
    assert decision.questions == ("Are any service-health outages active in this subscription?",)


def test_semantically_rejected_questions_never_reach_evaluation_ledger(
    subscription_health_contract: TypedQuestionContract,
) -> None:
    written: list[str] = []

    decision = admit_generated_question(
        challenge_id="service-outage",
        contract=subscription_health_contract,
        locale="en",
        attempts=3,
        propose=lambda attempt: {
            "question": f"Which exact resource has health incident {attempt}?",
            "locale": "en",
            "challenge_id": "service-outage",
        },
        review=lambda _question: _review_payload(
            subscription_health_contract,
            scope_kind="exact_resource",
            target_cardinality="single",
        ),
    )
    persisted = persist_admitted_questions(
        decision,
        lambda question: written.append(question),
    )

    assert not decision.accepted
    assert decision.attempts == 3
    assert decision.rejection_reasons == ("typed_contract_changed",) * 3
    assert persisted == ()
    assert written == []


def test_three_question_paraphrase_cohort_preserves_typed_contract(
    subscription_health_contract: TypedQuestionContract,
) -> None:
    paraphrases = [
        "Are service-health outages currently active in this subscription?",
        "Does this subscription have an active service-health outage?",
        "Any current service-health outage across the configured subscription?",
    ]

    decision = admit_paraphrase_cohort(
        challenge_id="service-outage",
        contract=subscription_health_contract,
        locale="en",
        original_question="Are any service-health outages active in this subscription?",
        attempts=1,
        propose=lambda _attempt: {
            "challenge_id": "service-outage",
            "questions": paraphrases,
        },
        review=lambda _question: _review_payload(subscription_health_contract),
    )

    assert decision.accepted
    assert decision.questions == tuple(paraphrases)


def test_paraphrase_cohort_retries_when_one_question_drifts(
    subscription_health_contract: TypedQuestionContract,
) -> None:
    proposals = (
        {
            "challenge_id": "service-outage",
            "questions": [
                "Are service-health outages currently active in this subscription?",
                "Which exact resource has a health incident?",
                "Any current service-health outage across the configured subscription?",
            ],
        },
        {
            "challenge_id": "service-outage",
            "questions": [
                "Are there active service-health outages in this subscription?",
                "Does the configured subscription have a service-health outage?",
                "Any service-health outage active across this subscription now?",
            ],
        },
    )
    reviews = iter(
        (
            _review_payload(subscription_health_contract),
            _review_payload(
                subscription_health_contract,
                scope_kind="exact_resource",
                target_cardinality="single",
            ),
            _review_payload(subscription_health_contract),
            _review_payload(subscription_health_contract),
            _review_payload(subscription_health_contract),
        )
    )

    decision = admit_paraphrase_cohort(
        challenge_id="service-outage",
        contract=subscription_health_contract,
        locale="en",
        original_question="Are any service-health outages active in this subscription?",
        attempts=2,
        propose=lambda attempt: proposals[attempt],
        review=lambda _question: next(reviews),
    )

    assert decision.accepted
    assert decision.attempts == 2
    assert decision.rejection_reasons == ("typed_contract_changed",)
    assert decision.questions == tuple(proposals[1]["questions"])


@pytest.mark.parametrize("attempts", [0, 4])
def test_question_admission_enforces_bounded_attempts(
    subscription_health_contract: TypedQuestionContract,
    attempts: int,
) -> None:
    with pytest.raises(ValueError, match="between 1 and 3"):
        admit_generated_question(
            challenge_id="service-outage",
            contract=subscription_health_contract,
            locale="en",
            attempts=attempts,
            propose=lambda _attempt: {},
            review=lambda _question: {},
        )
