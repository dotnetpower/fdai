#!/usr/bin/env python3
"""Generate a stable no-authority scorecard from measured ChatOps quality runs."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fdai.core.conversation_assurance.quality_qualification import (
    ChatOpsQualificationBatch,
    QualificationCorpus,
    QualificationEvidence,
    QualificationItemObservation,
    QualificationProvenance,
    QualificationRun,
    evaluate_chatops_qualification,
)
from fdai.core.conversation_assurance.quality_scorecard import QualityDimension

_ROOT_KEYS = frozenset({"schema_version", "qualification_id", "provenance", "corpus", "runs"})
_PROVENANCE_KEYS = frozenset(
    {
        "source_revision",
        "contract_version",
        "contract_digest",
        "runner_version",
        "evaluator_versions",
        "model_identifiers",
        "deployment_identifiers",
        "run_configuration_digest",
    }
)
_CORPUS_KEYS = frozenset(
    {
        "corpus_id",
        "corpus_version",
        "content_digest",
        "turn_count",
        "english_turns",
        "korean_turns",
    }
)
_RUN_KEYS = frozenset({"run_id", "started_at", "completed_at", "items"})
_ITEM_KEYS = frozenset({"item_id", "components", "evidence"})
_EVIDENCE_KEYS = frozenset(
    {
        "frozen_blind_corpus",
        "production_e2e",
        "latency_slo",
        "complete_trace",
        "critical_safety_escape",
    }
)
_COMPONENT_KEYS = frozenset(dimension.value for dimension in QualityDimension)


def evaluate_file(path: Path) -> dict[str, object]:
    """Load measured observations and return a deterministic qualification scorecard."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    batch = _batch(_mapping(raw, "root"))
    return evaluate_chatops_qualification(batch).to_dict()


def _batch(raw: Mapping[str, Any]) -> ChatOpsQualificationBatch:
    _require_exact_keys(raw, _ROOT_KEYS, "root")
    if raw["schema_version"] != "1.0.0":
        raise ValueError("schema_version MUST be 1.0.0")
    runs = raw["runs"]
    if not isinstance(runs, list):
        raise ValueError("runs MUST be an array")
    return ChatOpsQualificationBatch(
        qualification_id=_string(raw["qualification_id"], "qualification_id"),
        provenance=_provenance(_mapping(raw["provenance"], "provenance")),
        corpus=_corpus(_mapping(raw["corpus"], "corpus")),
        runs=tuple(_run(value, index) for index, value in enumerate(runs)),
    )


def _provenance(raw: Mapping[str, Any]) -> QualificationProvenance:
    _require_exact_keys(raw, _PROVENANCE_KEYS, "provenance")
    return QualificationProvenance(
        source_revision=_string(raw["source_revision"], "source_revision"),
        contract_version=_string(raw["contract_version"], "contract_version"),
        contract_digest=_string(raw["contract_digest"], "contract_digest"),
        runner_version=_string(raw["runner_version"], "runner_version"),
        evaluator_versions=_strings(raw["evaluator_versions"], "evaluator_versions"),
        model_identifiers=_strings(raw["model_identifiers"], "model_identifiers"),
        deployment_identifiers=_strings(raw["deployment_identifiers"], "deployment_identifiers"),
        run_configuration_digest=_string(
            raw["run_configuration_digest"], "run_configuration_digest"
        ),
    )


def _corpus(raw: Mapping[str, Any]) -> QualificationCorpus:
    _require_exact_keys(raw, _CORPUS_KEYS, "corpus")
    return QualificationCorpus(
        corpus_id=_string(raw["corpus_id"], "corpus_id"),
        corpus_version=_string(raw["corpus_version"], "corpus_version"),
        content_digest=_string(raw["content_digest"], "corpus.content_digest"),
        turn_count=_integer(raw["turn_count"], "turn_count"),
        english_turns=_integer(raw["english_turns"], "english_turns"),
        korean_turns=_integer(raw["korean_turns"], "korean_turns"),
    )


def _run(raw: object, index: int) -> QualificationRun:
    item = _mapping(raw, f"runs[{index}]")
    _require_exact_keys(item, _RUN_KEYS, f"runs[{index}]")
    observations = item["items"]
    if not isinstance(observations, list):
        raise ValueError(f"runs[{index}].items MUST be an array")
    return QualificationRun(
        run_id=_string(item["run_id"], f"runs[{index}].run_id"),
        started_at=_string(item["started_at"], f"runs[{index}].started_at"),
        completed_at=_string(item["completed_at"], f"runs[{index}].completed_at"),
        items=tuple(
            _observation(value, index, item_index) for item_index, value in enumerate(observations)
        ),
    )


def _observation(raw: object, run_index: int, item_index: int) -> QualificationItemObservation:
    field = f"runs[{run_index}].items[{item_index}]"
    item = _mapping(raw, field)
    _require_exact_keys(item, _ITEM_KEYS, field)
    components = _mapping(item["components"], f"{field}.components")
    _require_exact_keys(components, _COMPONENT_KEYS, f"{field}.components")
    evidence = _mapping(item["evidence"], f"{field}.evidence")
    _require_exact_keys(evidence, _EVIDENCE_KEYS, f"{field}.evidence")
    return QualificationItemObservation(
        item_id=_integer(item["item_id"], f"{field}.item_id"),
        components=tuple(
            (dimension, _number(components[dimension.value], f"{field}.{dimension.value}"))
            for dimension in QualityDimension
        ),
        evidence=QualificationEvidence(
            frozen_blind_corpus=_boolean(
                evidence["frozen_blind_corpus"], f"{field}.frozen_blind_corpus"
            ),
            production_e2e=_boolean(evidence["production_e2e"], f"{field}.production_e2e"),
            latency_slo=_boolean(evidence["latency_slo"], f"{field}.latency_slo"),
            complete_trace=_boolean(evidence["complete_trace"], f"{field}.complete_trace"),
            critical_safety_escape=_boolean(
                evidence["critical_safety_escape"], f"{field}.critical_safety_escape"
            ),
        ),
    )


def _mapping(raw: object, field: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise ValueError(f"{field} MUST be an object with string keys")
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
        raise ValueError(f"{field} MUST be a string")
    return raw


def _strings(raw: object, field: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or any(not isinstance(value, str) for value in raw):
        raise ValueError(f"{field} MUST be an array of strings")
    return tuple(raw)


def _integer(raw: object, field: str) -> int:
    if type(raw) is not int:
        raise ValueError(f"{field} MUST be an integer")
    return raw


def _number(raw: object, field: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{field} MUST be a number")
    return float(raw)


def _boolean(raw: object, field: str) -> bool:
    if type(raw) is not bool:
        raise ValueError(f"{field} MUST be a boolean")
    return raw


def main(argv: Sequence[str] | None = None) -> int:
    """Write a stable scorecard and optionally require complete qualification."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-qualified", action="store_true")
    args = parser.parse_args(argv)
    try:
        scorecard = evaluate_file(args.input)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"chatops-quality-qualification: ERROR: {exc}", file=sys.stderr)
        return 2
    serialized = json.dumps(scorecard, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(serialized)
    else:
        args.output.write_text(serialized, encoding="utf-8")
    if args.require_qualified and not scorecard["qualified"]:
        print("chatops-quality-qualification: NOT QUALIFIED", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
