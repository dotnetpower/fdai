from __future__ import annotations

from pathlib import Path

from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog, load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord

_ROOT = Path(__file__).resolve().parents[4]


def _catalog() -> OntologyCatalog:
    return load_ontology_catalog(
        _ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=_ROOT / "rule-catalog" / "probes",
    )


def test_existing_objects_and_minimal_links_answer_ohl_competencies() -> None:
    catalog = _catalog()
    object_names = {item.name for item in catalog.object_types}
    links = {item.name: item for item in catalog.link_types}

    assert "HypothesisCampaign" not in object_names
    assert {
        "DecisionCase",
        "ActionOption",
        "ExpectedEffect",
        "Experiment",
        "ActionRun",
        "ObservedOutcome",
        "CausalHypothesis",
        "EvidenceArtifact",
    } <= object_names
    assert {
        name: (links[name].from_type, links[name].to_type)
        for name in (
            "considers",
            "expects",
            "executed_as",
            "resulted_in",
            "outcome_tests_hypothesis",
            "evidence_supports_hypothesis",
            "evidence_refutes_hypothesis",
            "hypothesis_precedes_hypothesis",
            "hypothesis_informs_expected_effect",
        )
    } == {
        "considers": ("DecisionCase", "ActionOption"),
        "expects": ("ActionOption", "ExpectedEffect"),
        "executed_as": ("ActionOption", "ActionRun"),
        "resulted_in": ("ActionRun", "ObservedOutcome"),
        "outcome_tests_hypothesis": ("ObservedOutcome", "CausalHypothesis"),
        "evidence_supports_hypothesis": ("EvidenceArtifact", "CausalHypothesis"),
        "evidence_refutes_hypothesis": ("EvidenceArtifact", "CausalHypothesis"),
        "hypothesis_precedes_hypothesis": ("CausalHypothesis", "CausalHypothesis"),
        "hypothesis_informs_expected_effect": ("CausalHypothesis", "ExpectedEffect"),
    }


def test_one_replayable_graph_answers_the_five_frozen_questions() -> None:
    objects = {
        item.id: item
        for item in (
            OntologyObjectRecord(
                "case-1",
                "DecisionCase",
                {
                    "id": "case-1",
                    "target_ref": "workload-1",
                    "evidence_cutoff": "2026-08-12T00:00:00Z",
                    "context_digest": "sha256:context",
                    "no_action_baseline": {"metric": "latency_ms", "expected": 240.0},
                    "uncertainty": 0.1,
                    "status": "selected",
                    "created_at": "2026-08-12T00:00:00Z",
                },
            ),
            OntologyObjectRecord(
                "option-1",
                "ActionOption",
                {
                    "id": "option-1",
                    "decision_case_id": "case-1",
                    "action_type_ref": "ops.scale-out",
                    "arguments": {"replicas": 2},
                    "expected_effect_ref": "effect-1",
                    "preconditions": ["fresh_context"],
                    "option_kind": "intervention",
                },
            ),
            OntologyObjectRecord(
                "effect-1",
                "ExpectedEffect",
                {
                    "id": "effect-1",
                    "metric": "latency_ms",
                    "direction": "decrease",
                    "lower_bound": 80.0,
                    "upper_bound": 140.0,
                    "window_seconds": 300,
                    "uncertainty": 0.1,
                    "predictor_version": "challenger-logic:v2",
                    "created_at": "2026-08-12T00:00:00Z",
                },
            ),
            OntologyObjectRecord("run-1", "ActionRun", {"id": "run-1"}),
            OntologyObjectRecord(
                "outcome-1",
                "ObservedOutcome",
                {
                    "id": "outcome-1",
                    "action_run_id": "run-1",
                    "expected_effect_ref": "effect-1",
                    "verification": "independent",
                    "recovery_status": "not_required",
                    "observed_values": {"latency_ms": 110.0},
                    "telemetry_complete": True,
                    "scorable": True,
                    "observed_at": "2026-08-12T00:06:00Z",
                },
            ),
            OntologyObjectRecord(
                "hypothesis-1",
                "CausalHypothesis",
                {"id": "hypothesis-1", "closure": "confirmed"},
            ),
            OntologyObjectRecord(
                "hypothesis-2",
                "CausalHypothesis",
                {"id": "hypothesis-2", "closure": "inconclusive"},
            ),
            OntologyObjectRecord("support-1", "EvidenceArtifact", {"id": "support-1"}),
            OntologyObjectRecord("refute-1", "EvidenceArtifact", {"id": "refute-1"}),
        )
    }
    links = (
        OntologyLinkRecord("considers", "case-1", "option-1"),
        OntologyLinkRecord("expects", "option-1", "effect-1"),
        OntologyLinkRecord("executed_as", "option-1", "run-1"),
        OntologyLinkRecord("resulted_in", "run-1", "outcome-1"),
        OntologyLinkRecord("outcome_tests_hypothesis", "outcome-1", "hypothesis-2"),
        OntologyLinkRecord("evidence_supports_hypothesis", "support-1", "hypothesis-2"),
        OntologyLinkRecord("evidence_refutes_hypothesis", "refute-1", "hypothesis-2"),
        OntologyLinkRecord("hypothesis_precedes_hypothesis", "hypothesis-1", "hypothesis-2"),
        OntologyLinkRecord(
            "hypothesis_informs_expected_effect",
            "hypothesis-2",
            "effect-1",
        ),
    )

    outgoing = {(item.link_type, item.from_id): item.to_id for item in links}
    option = objects[outgoing[("considers", "case-1")]]
    effect = objects[outgoing[("expects", option.id)]]
    run = objects[outgoing[("executed_as", option.id)]]
    outcome = objects[outgoing[("resulted_in", run.id)]]
    hypothesis = objects[outgoing[("outcome_tests_hypothesis", outcome.id)]]
    support = {
        item.from_id
        for item in links
        if item.link_type == "evidence_supports_hypothesis" and item.to_id == hypothesis.id
    }
    refutation = {
        item.from_id
        for item in links
        if item.link_type == "evidence_refutes_hypothesis" and item.to_id == hypothesis.id
    }
    basis = next(
        item.from_id
        for item in links
        if item.link_type == "hypothesis_informs_expected_effect" and item.to_id == effect.id
    )

    assert objects["case-1"].properties["target_ref"] == "workload-1"
    assert option.properties["action_type_ref"] == "ops.scale-out"
    assert objects["case-1"].properties["no_action_baseline"]["expected"] == 240.0
    assert effect.properties["upper_bound"] == 140.0
    assert outcome.properties["verification"] == "independent"
    assert support == {"support-1"}
    assert refutation == {"refute-1"}
    assert objects[basis].id == "hypothesis-2"
    assert effect.properties["predictor_version"] == "challenger-logic:v2"
