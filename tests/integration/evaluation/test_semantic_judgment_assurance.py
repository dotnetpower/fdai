"""Frozen multilingual assurance for the shared semantic judgment boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fdai.core.conversation.semantic_judgment import (
    SemanticJudgmentBinding,
    SemanticJudgmentBoundary,
)
from fdai_service_contracts.semantic_judgment import SemanticJudgmentTier
from jsonschema import Draft202012Validator

_ROOT = Path(__file__).resolve().parents[3]
_DATASET = _ROOT / "eval/golden-dataset"
_DIGEST = "sha256:" + ("a" * 64)


class _FrozenTreatmentModel:
    def __init__(self, treatment: Mapping[str, Any]) -> None:
        self._treatment = dict(treatment)

    def judge(self, **_kwargs: object) -> Mapping[str, Any] | None:
        disposition = self._treatment["disposition"]
        if disposition in {"unavailable", "timeout"}:
            return None
        if disposition == "malformed":
            return {"invalid": True}
        ambiguous = disposition == "clarification"
        return {
            "schema_version": "1.0.0",
            "primary_intent": self._treatment["primary_intent"],
            "secondary_intents": self._treatment.get("secondary_intents", []),
            "targets": [],
            "requested_facets": self._treatment.get("requested_facets", []),
            "confidence": self._treatment["confidence"],
            "ambiguous": ambiguous,
            "alternatives": self._treatment.get("alternatives", []),
            "unresolved_terms": [],
            "clarification": self._treatment.get("clarification"),
            "discourse_mode": self._treatment["discourse_mode"],
            "action_posture": self._treatment["action_posture"],
            "authority": "candidate_only",
            "execution_authority": False,
        }


def _load(name: str) -> dict[str, Any]:
    return json.loads((_DATASET / name).read_text(encoding="utf-8"))


def _run(case: Mapping[str, Any]) -> tuple[str, Mapping[str, Any] | None]:
    boundary = SemanticJudgmentBoundary(
        profile_id="issue252-assurance",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_FrozenTreatmentModel(case["treatment"]),
            model_config_digest=_DIGEST,
            prompt_digest=_DIGEST,
        ),
    )
    result = boundary.judge(
        utterance=case["utterance"],
        context=case["context"],
        capabilities=({"kind": "assurance", "name": "issue252"},),
    )
    proposal = result.proposal.model_dump(mode="json") if result.proposal is not None else None
    assert result.receipt.execution_authority is False
    if proposal is not None:
        assert proposal["authority"] == "candidate_only"
        assert proposal["execution_authority"] is False
    return result.receipt.disposition.value, proposal


def test_semantic_judgment_assurance_schema_and_base_corpus() -> None:
    artifact = _load("semantic-judgment-assurance.json")
    schema = _load("semantic-judgment-assurance.schema.json")
    Draft202012Validator(schema).validate(artifact)

    expectations = _load("expectations.json")
    english = _load("questions.en.json")
    korean = _load("questions.ko.json")
    assert len(expectations["cases"]) == 35
    assert len(english["questions"]) == len(korean["questions"]) == 280
    assert artifact["base_dataset_version"] == expectations["dataset_version"]
    assert artifact["evidence_kind"] == "synthetic_contract_replay"
    assert artifact["operational_validation"] is False


def test_semantic_judgment_assurance_covers_required_language_failures() -> None:
    cases = _load("semantic-judgment-assurance.json")["cases"]
    assert {case["locale"] for case in cases} == {"en", "ko", "mixed"}
    assert {
        "paraphrase",
        "unseen_synonym",
        "negation_correction",
        "hypothetical_quoted",
        "prior_turn_omission",
        "multiple_intents",
        "adversarial_keyword_stuffing",
        "ambiguity",
        "model_failure",
    } <= {case["dimension"] for case in cases}
    assert {case["treatment"]["disposition"] for case in cases} >= {
        "unavailable",
        "timeout",
        "malformed",
        "low_confidence",
    }


def test_structured_boundary_exceeds_frozen_lexical_baseline() -> None:
    artifact = _load("semantic-judgment-assurance.json")
    cases = artifact["cases"]
    expected_semantic = [case for case in cases if case["expected"]["disposition"] == "accepted"]
    legacy_predictions = [case for case in cases if case["legacy"]["primary_intent"] is not None]
    legacy_correct = sum(
        case["legacy"]["primary_intent"] == case["expected"]["primary_intent"]
        and case["expected"]["disposition"] == "accepted"
        for case in cases
    )
    assert expected_semantic, "semantic assurance requires accepted intent cases"
    assert legacy_predictions, "semantic assurance requires lexical baseline predictions"
    legacy_recall = legacy_correct / len(expected_semantic)
    legacy_precision = legacy_correct / len(legacy_predictions)

    treatment_correct = 0
    treatment_predictions = 0
    terminal_correct = 0
    terminal_total = 0
    authority_violations = 0
    lexical_fallbacks = 0
    dimension_results: dict[str, list[bool]] = {}
    for case in cases:
        disposition, proposal = _run(case)
        expected = case["expected"]
        treatment_predictions += int(disposition == "accepted")
        if expected["disposition"] == "accepted":
            case_correct = (
                disposition == "accepted"
                and proposal is not None
                and proposal["primary_intent"] == expected["primary_intent"]
                and proposal["secondary_intents"] == expected["secondary_intents"]
                and proposal["discourse_mode"] == expected["discourse_mode"]
                and proposal["action_posture"] == expected["action_posture"]
            )
            treatment_correct += int(case_correct)
        else:
            terminal_total += 1
            case_correct = disposition == expected["disposition"]
            terminal_correct += int(case_correct)
            lexical_fallbacks += int(disposition == "accepted")
        dimension_results.setdefault(case["dimension"], []).append(case_correct)
        authority_violations += int(
            proposal is not None and proposal["execution_authority"] is not False
        )

    assert treatment_predictions, "semantic assurance requires accepted treatment predictions"
    assert terminal_total, "semantic assurance requires fail-closed terminal cases"
    treatment_recall = treatment_correct / len(expected_semantic)
    treatment_precision = treatment_correct / treatment_predictions
    terminal_accuracy = terminal_correct / terminal_total
    thresholds = artifact["thresholds"]
    assert treatment_recall > legacy_recall
    assert treatment_precision > legacy_precision
    assert treatment_recall >= thresholds["semantic_recall_min"]
    assert treatment_precision >= thresholds["semantic_precision_min"]
    assert all(
        sum(results) / len(results) >= thresholds["per_dimension_accuracy_min"]
        for results in dimension_results.values()
    )
    assert terminal_accuracy >= thresholds["terminal_outcome_accuracy_min"]
    assert authority_violations <= thresholds["authority_violations_max"]
    assert lexical_fallbacks <= thresholds["lexical_fallbacks_max"]
