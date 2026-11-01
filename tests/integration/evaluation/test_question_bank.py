"""Contract tests for the reviewable FDAI question bank."""

from __future__ import annotations

import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from scripts.automation import build_question_bank as generator
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
    assert payload["summary"]["question_count"] == 400
    assert payload["summary"]["source_counts"] == {
        "candidate": 300,
        "console": 5,
        "golden": 35,
        "manual": 60,
    }
    assert len(payload["source_files"]) == 11


def test_question_bank_check_is_non_mutating_and_detects_catalog_source_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for record in _artifact()["source_files"]:
        relative = Path(record["path"])
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_ROOT / relative, destination)
    for schema in _BANK_ROOT.glob("*.schema.json"):
        shutil.copyfile(schema, tmp_path / schema.relative_to(_ROOT))
    output = tmp_path / "eval/golden-dataset/question-bank/question-bank.json"
    monkeypatch.setattr(
        sys, "argv", ["build_question_bank.py", "--repo-root", str(tmp_path), "--check"]
    )
    assert generator.main() == 1
    assert not output.exists()
    monkeypatch.setattr(sys, "argv", ["build_question_bank.py", "--repo-root", str(tmp_path)])
    assert generator.main() == 0
    retained = output.read_bytes()
    monkeypatch.setattr(
        sys, "argv", ["build_question_bank.py", "--repo-root", str(tmp_path), "--check"]
    )
    assert generator.main() == 0
    catalog = tmp_path / "console/src/i18n/messages.en.json"
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    payload["question_bank_source_drift_probe"] = "an unrelated localized string"
    catalog.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert generator.main() == 1
    assert output.read_bytes() == retained


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
        "deck.starterSuggestions.screen",
        "deck.starterSuggestions.tierMix",
        "deck.verticalQuickStarts.changeSafetyPrompt",
        "deck.verticalQuickStarts.costGovernancePrompt",
        "deck.verticalQuickStarts.resiliencePrompt",
    }
    assert all(
        question["readiness"]
        == {
            "content_review": "reviewed",
            "semantic_contract": "covered",
            "runtime_binding": "bound",
            "evidence_source": "retained",
            "validation": "contract_passed",
        }
        for question in console
    )
    by_legacy_id = {question["legacy_ids"][0]: question for question in console}
    assert {key: value["intent"] for key, value in by_legacy_id.items()} == {
        "deck.starterSuggestions.screen": "query.subscription_service_health",
        "deck.starterSuggestions.tierMix": "query.resource_state_inventory",
        "deck.verticalQuickStarts.changeSafetyPrompt": "query.resource_health_inventory",
        "deck.verticalQuickStarts.costGovernancePrompt": "query.resource_state_inventory",
        "deck.verticalQuickStarts.resiliencePrompt": "query.resource_state_inventory",
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
        question["readiness"]["content_review"] == "reviewed"
        and question["readiness"]["semantic_contract"] == "covered"
        and question["readiness"]["runtime_binding"] in {"bound", "clarify"}
        and question["readiness"]["evidence_source"] == "contract_only"
        and question["readiness"]["validation"] == "contract_passed"
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
    assert all(question["readiness"]["content_review"] == "reviewed" for question in expansion)
    assert all(question["readiness"]["validation"] == "contract_passed" for question in expansion)
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


def test_current_resource_questions_cover_observed_generic_resource_types() -> None:
    source_ref = "eval/golden-dataset/question-bank/current-resource-sre-questions.source.yaml"
    questions = [
        question for question in _artifact()["questions"] if question["source_refs"] == [source_ref]
    ]
    expected_target_kinds = {
        "ApplicationInsightsComponent",
        "AzureMonitorWorkspace",
        "BastionHost",
        "CognitiveServicesAccount",
        "ContainerRegistry",
        "KeyVault",
        "LogAnalyticsWorkspace",
        "ManagedDisk",
        "ManagedGrafana",
        "ManagedIdentity",
        "NetworkInterface",
        "NetworkSecurityGroup",
        "PrivateDnsZone",
        "PublicIPAddress",
        "SmartDetectorAlertRule",
        "StorageAccount",
        "VirtualMachine",
        "VirtualNetwork",
        "VirtualNetworkLink",
    }

    assert len(questions) == 50
    assert expected_target_kinds <= {
        target_kind for question in questions for target_kind in question["target_kinds"]
    }
    assert all(question["required_context"] == "server_scope" for question in questions)
    assert all(question["safety"]["action_posture"] == "read_only" for question in questions)
    assert all(question["safety"]["execution_authority"] is False for question in questions)


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


def test_question_bank_40_rounds_of_10_questions_satisfy_bilingual_and_safety_invariants() -> None:
    questions = _artifact()["questions"]
    assert len(questions) == 400
    rounds = [questions[index : index + 10] for index in range(0, 400, 10)]
    assert len(rounds) == 40
    for round_index, batch in enumerate(rounds, start=1):
        assert len(batch) == 10, f"round {round_index} must contain 10 questions"
        for item in batch:
            assert item["question_id"].strip()
            assert item["intent"].strip()
            assert item["wording"]["en"].strip()
            assert item["wording"]["ko"].strip()
            assert item["safety"]["execution_authority"] is False
            assert set(item["readiness"]) == {
                "content_review",
                "semantic_contract",
                "runtime_binding",
                "evidence_source",
                "validation",
            }


def test_question_bank_100_rounds_achieve_100_percent_bilingual_and_oracle_coverage() -> None:
    from fdai.core.conversation.semantic_judgment import (
        SemanticJudgmentBinding,
        SemanticJudgmentBoundary,
    )
    from fdai_operator_service.families.conversation.presentation_artifact_renderers import (
        _compile_block,
    )
    from fdai_operator_service.families.conversation.presentation_planner import (
        PresentationIntent,
        PresentationKind,
        analyze_evidence_shape,
        plan_presentation,
    )
    from fdai_service_contracts.semantic_judgment import (
        SemanticJudgmentDisposition,
        SemanticJudgmentTier,
    )
    from scripts.automation.question_bank_contracts import (
        ALL_PANTHEON_DOMAINS,
        ALL_QUERY_FUNCTIONS,
    )

    digest = "sha256:" + ("a" * 64)

    class _ParaphraseInvariantModel:
        def __init__(self, intent: str, action_posture: str) -> None:
            self._intent = intent
            self._action_posture = action_posture

        def judge(self, **_kwargs: object) -> dict[str, object]:
            return {
                "schema_version": "1.0.0",
                "primary_intent": self._intent,
                "secondary_intents": [],
                "targets": [],
                "requested_facets": ["current_state"],
                "confidence": 0.96,
                "ambiguous": False,
                "alternatives": [],
                "unresolved_terms": [],
                "clarification": None,
                "discourse_mode": "direct",
                "action_posture": self._action_posture,
                "action_subject": "ActionType" if self._action_posture == "draft_only" else "none",
                "authority": "candidate_only",
                "execution_authority": False,
            }

    questions = _artifact()["questions"]
    assert len(questions) == 400
    rounds = [questions[index : index + 4] for index in range(0, 400, 4)]
    assert len(rounds) == 100

    covered_functions: set[str] = set()
    covered_pantheon: set[str] = set()
    shape = analyze_evidence_shape(
        {
            "source_complete": True,
            "total_rows": 2,
            "returned_rows": 2,
            "rows": [
                {
                    "values": {
                        "name": "vm-01",
                        "status": "Running",
                        "value": 42.5,
                        "baseline": 30.0,
                        "observed_at": "2026-11-01T00:00:00Z",
                        "execution_authority": False,
                    }
                },
                {
                    "values": {
                        "name": "vm-02",
                        "status": "Degraded",
                        "value": 85.0,
                        "baseline": 40.0,
                        "observed_at": "2026-11-01T00:05:00Z",
                        "execution_authority": False,
                    }
                },
            ],
        },
        verified=True,
    )

    for round_number, batch in enumerate(rounds, start=1):
        assert len(batch) == 4, f"round {round_number} must contain 4 questions"
        for item in batch:
            assert item["readiness"]["content_review"] == "reviewed"
            assert item["readiness"]["validation"] == "contract_passed"
            assert item["paired_model_case"]["pair_profile"] == "t1_active_vs_challenger"
            covered_functions.update(item["required_function_types"])
            covered_pantheon.update(item["pantheon_domains"])

            oracle = item["presentation_oracle"]
            intent_enum = PresentationIntent(oracle["intent"])
            kind_enum = PresentationKind(oracle["primary_kind"])
            assert kind_enum in set(PresentationKind)
            decision = plan_presentation(intent=intent_enum, shape=shape)
            assert decision.kind in set(PresentationKind)
            for locale in ("en", "ko"):
                block = _compile_block(
                    decision.kind,
                    reason_code=decision.reason_code,
                    shape=shape,
                    locale=locale,
                    evidence_refs=["ref:1"],
                    visualization=decision.visualization,
                )
                assert block is not None

            intent = str(item["intent"])
            raw_posture = str(item["safety"]["action_posture"])
            posture = "draft_only" if raw_posture == "draft_only" else "advise_only"
            digest_b = "sha256:" + ("b" * 64)
            for profile_id in ("t1_compact_active", "t1_challenger_shadow"):
                boundary = SemanticJudgmentBoundary(
                    profile_id=profile_id,
                    profile_version="1.0.0",
                    primary=SemanticJudgmentBinding(
                        tier=SemanticJudgmentTier.T1,
                        model=_ParaphraseInvariantModel(intent, posture),
                        model_config_digest=digest,
                        prompt_digest=digest,
                    ),
                    escalation=SemanticJudgmentBinding(
                        tier=SemanticJudgmentTier.T2,
                        model=_ParaphraseInvariantModel(intent, posture),
                        model_config_digest=digest_b,
                        prompt_digest=digest_b,
                    ),
                )
                for locale in ("en", "ko"):
                    variations = item["variations"][locale]
                    assert len(variations) >= 1
                    utterances = [item["wording"][locale], *(v["text"] for v in variations)]
                    for utterance in utterances:
                        res = boundary.judge(
                            utterance=utterance,
                            context=(),
                            capabilities=({"kind": "assurance", "name": intent},),
                            allow_escalation=False,
                            locale=locale,
                        )
                        assert res.receipt.disposition is SemanticJudgmentDisposition.ACCEPTED
                        assert res.proposal is not None
                        assert res.proposal.primary_intent == intent
                        assert res.proposal.action_posture == posture
                        assert res.proposal.execution_authority is False

    assert covered_functions == set(ALL_QUERY_FUNCTIONS)
    assert covered_pantheon == set(ALL_PANTHEON_DOMAINS)
