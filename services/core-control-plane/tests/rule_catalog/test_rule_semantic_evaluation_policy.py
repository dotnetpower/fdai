from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fdai.rule_catalog.schema.rule_semantic_evaluation_policy import (
    EvaluationPolicyLoadError,
    load_retrieval_evaluation_policy_from_json,
    load_retrieval_evaluation_policy_from_mapping,
)

_ROOT = Path(__file__).resolve().parents[4]
_CONFIG = _ROOT / "config" / "rule-semantic-evaluation.json"


def test_shipped_evaluation_policy_is_schema_valid_and_content_addressed() -> None:
    raw = _CONFIG.read_text(encoding="utf-8")

    first = load_retrieval_evaluation_policy_from_json(raw)
    second = load_retrieval_evaluation_policy_from_mapping(json.loads(raw))

    assert first == second
    assert first.digest == second.digest
    assert first.digest.startswith("sha256:")
    assert first.required_cohorts == tuple(sorted(first.required_cohorts))
    assert "ko-positive" in first.required_cohorts
    assert "adversarial-negative" in first.required_cohorts
    assert "stale-active-generation" in first.required_cohorts


def test_sample_floor_preserves_legacy_identity_and_binds_new_policy() -> None:
    raw = json.loads(_CONFIG.read_text(encoding="utf-8"))
    legacy = load_retrieval_evaluation_policy_from_mapping(raw)
    assert (
        legacy.digest
        == "sha256:"
        + hashlib.sha256(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    policy = load_retrieval_evaluation_policy_from_mapping(
        {**raw, "schema_version": "1.1.0", "min_samples_per_metric": 20}
    )
    assert policy.min_samples_per_metric == 20
    assert policy.digest != legacy.digest
    assert replace(policy, min_samples_per_metric=21).digest != policy.digest


@pytest.mark.parametrize("floor", [None, True, 0, 1, 2.5, 10001])
def test_sample_floor_requires_explicit_bounded_integer(floor: object) -> None:
    raw = json.loads(_CONFIG.read_text(encoding="utf-8"))
    raw["schema_version"] = "1.1.0"
    if floor is not None:
        raw["min_samples_per_metric"] = floor
    with pytest.raises(EvaluationPolicyLoadError):
        load_retrieval_evaluation_policy_from_mapping(raw)


def test_legacy_policy_rejects_unversioned_sample_floor() -> None:
    raw = json.loads(_CONFIG.read_text(encoding="utf-8"))
    with pytest.raises(EvaluationPolicyLoadError):
        load_retrieval_evaluation_policy_from_mapping({**raw, "min_samples_per_metric": 20})
    with pytest.raises(ValueError, match="legacy"):
        replace(load_retrieval_evaluation_policy_from_mapping(raw), min_samples_per_metric=20)


def test_evaluation_policy_rejects_schema_and_domain_violations() -> None:
    with pytest.raises(EvaluationPolicyLoadError) as schema_error:
        load_retrieval_evaluation_policy_from_mapping(
            {
                "schema_version": "1.0.0",
                "top_k": 0,
                "min_recall_at_k": 2.0,
                "min_mean_reciprocal_rank": 1.0,
                "min_no_match_precision": 1.0,
                "required_cohorts": ["en-positive"],
                "unknown": True,
            }
        )
    assert {item.key for item in schema_error.value.issues} == {
        "<root>",
        "min_recall_at_k",
        "top_k",
    }

    with pytest.raises(EvaluationPolicyLoadError, match="unique, and ordered"):
        load_retrieval_evaluation_policy_from_mapping(
            {
                "schema_version": "1.0.0",
                "top_k": 5,
                "min_recall_at_k": 1.0,
                "min_mean_reciprocal_rank": 1.0,
                "min_no_match_precision": 1.0,
                "required_cohorts": ["ko-positive", "en-positive"],
            }
        )


@pytest.mark.parametrize("raw", ("{", "[]"))
def test_evaluation_policy_rejects_malformed_or_non_object_json(raw: str) -> None:
    with pytest.raises(EvaluationPolicyLoadError):
        load_retrieval_evaluation_policy_from_json(raw)
