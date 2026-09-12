"""Contract tests for the generated semantic-intent coverage inventory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from scripts.automation.build_semantic_intent_coverage import _ratio, build_inventory

_ROOT = Path(__file__).resolve().parents[3]
_ARTIFACT = _ROOT / "eval/golden-dataset/semantic-intent-coverage.json"


def _artifact() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(_ARTIFACT.read_text(encoding="utf-8")),
    )


def test_semantic_intent_coverage_artifact_matches_authoritative_sources() -> None:
    assert _artifact() == build_inventory(_ROOT)


def test_semantic_intent_inventory_exposes_complete_topic_denominators() -> None:
    payload = _artifact()
    topics = payload["topic_inventory"]

    assert payload["schema_version"] == "1.1.0"
    assert payload["scorecard"] == {
        "id": "fdai-conversation-quality-assurance",
        "name": "FDAI Conversation Quality Assurance Scorecard",
        "acronym": "CQAS",
        "aggregation": "conjunctive",
        "metric_count": 93,
        "pillars": {
            "question_understanding": [
                "intent",
                "target",
                "ambiguity",
                "discourse_and_action",
                "time_and_evidence",
                "locale_and_robustness",
                "authority",
            ],
            "answer_fidelity": ["answer_fidelity"],
            "presentation_quality": ["presentation_quality"],
            "model_invariance": ["model_invariance"],
        },
    }
    assert len(topics["operating_domains"]) == 4
    assert len(topics["question_bank_domains"]) == 7
    assert len(topics["golden_categories"]) == 12
    assert len(topics["pantheon_question_domains"]) == 47
    assert len(topics["ontology_query_functions"]) == 37
    assert len({item["agent"] for item in topics["pantheon_question_domains"]}) == 15
    assert all(item["coverage_state"] == "unmapped" for item in topics["pantheon_question_domains"])
    functions = {item["topic_id"]: item for item in topics["ontology_query_functions"]}
    assert functions["query.resource_health_inventory"]["intent_contract_case_count"] == 0
    assert functions["query.resource_current_state"]["intent_contract_case_count"] > 0
    assert payload["coverage_metrics"]["ontology_query_function_any_contract_coverage"] == {
        "covered": 12,
        "total": 37,
        "rate": 12 / 37,
    }


def test_semantic_intent_metrics_fail_closed_on_unsupported_slices() -> None:
    payload = _artifact()
    metrics = [metric for group in payload["metric_contract"].values() for metric in group]
    by_name = {metric["name"]: metric for metric in metrics}

    assert len(by_name) == len(metrics)
    assert len(metrics) == 93
    assert payload["scoring_policy"]["empty_denominator"].startswith("not_scored")
    assert set(payload["hard_zero_metrics"]) <= set(by_name)
    assert all(by_name[name]["promotion_target"] == 0 for name in payload["hard_zero_metrics"])
    assert payload["coverage_metrics"]["pantheon_domain_semantic_contract_coverage"] == {
        "covered": 0,
        "total": 47,
        "rate": 0.0,
    }
    assert _ratio(0, 0) == {"covered": 0, "total": 0, "rate": None}


def test_answer_and_presentation_rubrics_follow_runtime_contracts() -> None:
    payload = _artifact()
    axes = payload["evaluation_axes"]
    coverage = payload["coverage_metrics"]

    assert axes["answer_adequacy_gates"] == [
        "authority",
        "calibration",
        "completeness",
        "evidence_entailment",
        "scope",
        "semantic",
    ]
    assert axes["answer_review_criteria"] == [
        "actionability",
        "calibration",
        "clarity",
        "completeness",
        "factual_correctness",
        "intent_resolution",
    ]
    assert len(axes["presentation_intents"]) == 12
    assert len(axes["presentation_kinds"]) == 13
    assert len(axes["presentation_semantic_shapes"]) == 10
    assert len(axes["visualization_kinds"]) == 11
    assert axes["presentation_layouts"] == [
        "markdown_document",
        "operational_brief",
        "stack",
    ]
    assert axes["responsive_policies"] == ["reflow", "scroll", "stack"]
    assert axes["accessibility_fallbacks"] == [
        "description-list",
        "exact-table",
        "ordered-list",
    ]
    assert coverage["golden_answer_oracle_coverage"] == {
        "covered": 35,
        "total": 35,
        "rate": 1.0,
    }
    assert coverage["presentation_block_registry_coverage"] == {
        "covered": 13,
        "total": 13,
        "rate": 1.0,
    }
    assert coverage["question_presentation_oracle_coverage"] == {
        "covered": 0,
        "total": 400,
        "rate": 0.0,
    }
    assert coverage["paired_model_case_coverage"] == {
        "covered": 0,
        "total": 400,
        "rate": 0.0,
    }
