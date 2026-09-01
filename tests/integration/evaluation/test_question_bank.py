"""Contract tests for the reviewable FDAI question bank."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, cast

import yaml
from scripts.automation.question_bank import build_question_bank, render_review_catalog

_ROOT = Path(__file__).resolve().parents[3]
_BANK_ROOT = _ROOT / "eval" / "golden-dataset" / "question-bank"
_SOURCE = _BANK_ROOT / "question-bank.source.yaml"


def _artifact() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((_BANK_ROOT / "question-bank.json").read_text(encoding="utf-8")),
    )


def test_question_bank_generated_artifacts_match_all_sources() -> None:
    payload = build_question_bank(repo_root=_ROOT, source_path=_SOURCE)

    assert payload == _artifact()
    assert render_review_catalog(payload) == (_BANK_ROOT / "review-catalog.md").read_text(
        encoding="utf-8"
    )
    assert payload["summary"]["question_count"] == 352
    assert payload["summary"]["source_counts"] == {
        "candidate": 250,
        "console": 7,
        "golden": 35,
        "manual": 60,
    }
    assert len(payload["source_files"]) == 10


def test_question_bank_preserves_existing_question_identities_and_variations() -> None:
    questions = _artifact()["questions"]
    by_source: dict[str, list[dict[str, Any]]] = {}
    for question in questions:
        by_source.setdefault(question["source_kind"], []).append(question)

    golden = by_source["golden"]
    assert {question["legacy_ids"][0] for question in golden} == {
        question["intent"] for question in golden
    }
    assert all(len(question["variations"]["en"]) == 8 for question in golden)
    assert all(len(question["variations"]["ko"]) == 8 for question in golden)

    manual = by_source["manual"]
    assert {legacy_id for question in manual for legacy_id in question["legacy_ids"]} == {
        f"Q{number:03d}" for number in range(1, 121)
    }
    assert all(len(question["variations"]["en"]) == 3 for question in manual)
    assert all(len(question["variations"]["ko"]) == 3 for question in manual)

    console = by_source["console"]
    assert {question["legacy_ids"][0] for question in console} == {
        "deck.starterSuggestions.approval",
        "deck.starterSuggestions.denied",
        "deck.starterSuggestions.failed",
        "deck.starterSuggestions.routes",
        "deck.starterSuggestions.screen",
        "deck.starterSuggestions.stuck",
        "deck.starterSuggestions.tierMix",
    }


def test_operator_candidates_cover_six_domains_with_fail_closed_readiness() -> None:
    candidates = [
        question
        for question in _artifact()["questions"]
        if question["source_kind"] == "candidate"
        and question["source_refs"]
        == ["eval/golden-dataset/question-bank/question-bank.source.yaml"]
    ]

    assert Counter(question["domain"] for question in candidates) == {
        "state_incident_detection": 10,
        "root_cause_analysis": 10,
        "change_deployment_impact": 10,
        "dependency_impact": 8,
        "capacity_performance_forecast": 7,
        "reliability_policy_automation": 5,
    }
    assert all(
        question["readiness"]
        == {
            "content_review": "candidate",
            "semantic_contract": "unassessed",
            "runtime_binding": "unassessed",
            "evidence_source": "unassessed",
            "validation": "not_run",
        }
        for question in candidates
    )
    assert all(question["safety"]["execution_authority"] is False for question in candidates)
    assert all(question["wording"]["en"].strip() for question in candidates)
    assert all(question["wording"]["ko"].strip() for question in candidates)


def test_action_advice_never_becomes_execution_authority() -> None:
    candidates = {
        question["question_id"]: question
        for question in _artifact()["questions"]
        if question["source_kind"] == "candidate"
        and question["source_refs"]
        == ["eval/golden-dataset/question-bank/question-bank.source.yaml"]
    }
    advice_ids = {
        "change.deployment-go-no-go",
        "reliability.safe-action-eligibility",
        "reliability.recovery-recommendations",
        "reliability.automatic-recovery-readiness",
    }

    assert {
        question_id
        for question_id, question in candidates.items()
        if question["safety"]["action_posture"] == "advise_only"
    } == advice_ids
    assert all(
        candidates[question_id]["safety"]["execution_authority"] is False
        for question_id in advice_ids
    )


def test_operator_expansion_preserves_all_200_supplied_questions() -> None:
    expansion_ref = "eval/golden-dataset/question-bank/operator-question-expansion.source.yaml"
    expansion = [
        question
        for question in _artifact()["questions"]
        if question["source_refs"] == [expansion_ref]
    ]

    assert len(expansion) == 200
    assert Counter(question["category"] for question in expansion) == {
        "current_health": 20,
        "incident": 20,
        "root_cause": 20,
        "metrics_observability": 15,
        "aks_kubernetes": 20,
        "azure_infrastructure_network": 15,
        "database_storage": 15,
        "cost_finops": 20,
        "capacity_scaling": 15,
        "prediction": 15,
        "dependency_impact": 15,
        "change_deployment_release": 10,
    }
    assert all(question["readiness"]["content_review"] == "candidate" for question in expansion)
    assert all(question["safety"]["execution_authority"] is False for question in expansion)
    assert {
        question["question_id"]: question["duplicate_of"]
        for question in expansion
        if "duplicate_of" in question
    } == {
        "change-deployment-release.deployment-incident-cause-analysis": (
            "root-cause.deployment-incident-correlation"
        ),
        "dependency-impact.db-failure-impact": "database-storage.db-failure-impact",
    }
    by_id = {question["question_id"]: question for question in expansion}
    for question in expansion:
        if "duplicate_of" in question:
            assert question["duplicate_of"] in by_id


def test_operator_expansion_preserves_supplied_category_order_and_unique_intents() -> None:
    payload = yaml.safe_load(
        (_BANK_ROOT / "operator-question-expansion.source.yaml").read_text(encoding="utf-8")
    )
    questions = payload["questions"]
    category_order = list(dict.fromkeys(question["category"] for question in questions))

    assert category_order == [
        "current_health",
        "incident",
        "root_cause",
        "metrics_observability",
        "aks_kubernetes",
        "azure_infrastructure_network",
        "database_storage",
        "cost_finops",
        "capacity_scaling",
        "prediction",
        "dependency_impact",
        "change_deployment_release",
    ]
    assert len({question["id"] for question in questions}) == 200
    assert len({question["intent"] for question in questions}) == 200


def test_operator_candidates_remain_customer_agnostic() -> None:
    candidates = [
        question for question in _artifact()["questions"] if question["source_kind"] == "candidate"
    ]
    wording = "\n".join(
        question["wording"][locale] for question in candidates for locale in ("en", "ko")
    ).casefold()

    assert "/subscriptions/" not in wording
    assert "/resourcegroups/" not in wording
    assert ".azure.com" not in wording
    assert (
        re.search(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
            wording,
        )
        is None
    )
    assert re.search(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", wording) is None
