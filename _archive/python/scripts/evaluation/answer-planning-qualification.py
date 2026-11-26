#!/usr/bin/env python3
"""Evaluate one sealed bilingual Answer Planning measurement batch."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fdai.core.conversation.answer_planning_qualification import (
    AnswerPlanningEvaluationBatch,
    AnswerPlanningEvaluationSample,
    PlanningEvaluationLocale,
    evaluate_answer_planning_qualification,
)

_BATCH_KEYS = frozenset({"scenario_set_version", "runner_version", "samples"})
_SAMPLE_KEYS = frozenset(
    {
        "case_id",
        "locale",
        "baseline_unique_evidence_count",
        "candidate_unique_evidence_count",
        "baseline_correction_required",
        "candidate_correction_required",
        "baseline_follow_up_required",
        "candidate_follow_up_required",
        "unsupported_claim_escape",
        "authority_violation",
        "clean_answer_regression",
        "planning_elapsed_ms",
        "added_tokens",
    }
)


def evaluate_file(path: Path) -> dict[str, object]:
    """Load measured observations and return a no-authority readiness receipt."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    batch = _batch(_mapping(raw, "batch"))
    receipt = evaluate_answer_planning_qualification(batch)
    return {
        "schema_version": "1.0.0",
        "evidence_kind": "measured_answer_planning_qualification",
        "activation_authority": False,
        **asdict(receipt),
    }


def _batch(raw: Mapping[str, Any]) -> AnswerPlanningEvaluationBatch:
    _require_exact_keys(raw, _BATCH_KEYS, "batch")
    samples = raw["samples"]
    if not isinstance(samples, list):
        raise ValueError("batch.samples must be an array")
    return AnswerPlanningEvaluationBatch(
        scenario_set_version=_string(raw["scenario_set_version"], "scenario_set_version"),
        runner_version=_string(raw["runner_version"], "runner_version"),
        samples=tuple(_sample(item, index) for index, item in enumerate(samples)),
    )


def _sample(raw: object, index: int) -> AnswerPlanningEvaluationSample:
    item = _mapping(raw, f"samples[{index}]")
    _require_exact_keys(item, _SAMPLE_KEYS, f"samples[{index}]")
    return AnswerPlanningEvaluationSample(
        case_id=_string(item["case_id"], f"samples[{index}].case_id"),
        locale=PlanningEvaluationLocale(_string(item["locale"], f"samples[{index}].locale")),
        baseline_unique_evidence_count=_integer(
            item["baseline_unique_evidence_count"],
            f"samples[{index}].baseline_unique_evidence_count",
        ),
        candidate_unique_evidence_count=_integer(
            item["candidate_unique_evidence_count"],
            f"samples[{index}].candidate_unique_evidence_count",
        ),
        baseline_correction_required=_boolean(
            item["baseline_correction_required"],
            f"samples[{index}].baseline_correction_required",
        ),
        candidate_correction_required=_boolean(
            item["candidate_correction_required"],
            f"samples[{index}].candidate_correction_required",
        ),
        baseline_follow_up_required=_boolean(
            item["baseline_follow_up_required"],
            f"samples[{index}].baseline_follow_up_required",
        ),
        candidate_follow_up_required=_boolean(
            item["candidate_follow_up_required"],
            f"samples[{index}].candidate_follow_up_required",
        ),
        unsupported_claim_escape=_boolean(
            item["unsupported_claim_escape"],
            f"samples[{index}].unsupported_claim_escape",
        ),
        authority_violation=_boolean(
            item["authority_violation"],
            f"samples[{index}].authority_violation",
        ),
        clean_answer_regression=_boolean(
            item["clean_answer_regression"],
            f"samples[{index}].clean_answer_regression",
        ),
        planning_elapsed_ms=_integer(
            item["planning_elapsed_ms"], f"samples[{index}].planning_elapsed_ms"
        ),
        added_tokens=_integer(item["added_tokens"], f"samples[{index}].added_tokens"),
    )


def _mapping(raw: object, field: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise ValueError(f"{field} must be an object with string keys")
    return raw


def _require_exact_keys(raw: Mapping[str, Any], expected: frozenset[str], field: str) -> None:
    actual = frozenset(raw)
    if actual != expected:
        raise ValueError(
            f"{field} fields differ: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


def _string(raw: object, field: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{field} must be a string")
    return raw


def _integer(raw: object, field: str) -> int:
    if type(raw) is not int:
        raise ValueError(f"{field} must be an integer")
    return raw


def _boolean(raw: object, field: str) -> bool:
    if type(raw) is not bool:
        raise ValueError(f"{field} must be a boolean")
    return raw


def main(argv: Sequence[str] | None = None) -> int:
    """Write a stable receipt and optionally require review readiness."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = evaluate_file(args.input)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"answer-planning-qualification: ERROR: {exc}", file=sys.stderr)
        return 2
    serialized = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(serialized)
    else:
        args.output.write_text(serialized, encoding="utf-8")
    if args.require_ready and not receipt["ready_for_review"]:
        print("answer-planning-qualification: NOT READY", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
