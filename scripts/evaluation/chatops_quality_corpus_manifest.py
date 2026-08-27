#!/usr/bin/env python3
"""Validate a content-free manifest for the hidden ChatOps qualification corpus."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.evaluation.chatops_quality_corpus import (
    CorpusManifestError,
    CoverageTag,
    HiddenCorpusCase,
    HiddenCorpusManifest,
    Locale,
    ReviewProtocol,
    summary,
)

_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "corpus_id",
        "corpus_version",
        "frozen_at",
        "freeze_revision",
        "qualification_contract_version",
        "qualification_contract_digest",
        "restricted_artifact_id",
        "hidden_payload_digest",
        "review_protocol",
        "rubric_observation_floors",
        "cases",
    }
)
_PROTOCOL_KEYS = frozenset(
    {
        "labeling_protocol_version",
        "evaluator_set_version",
        "run_configuration_version",
        "confidence_method",
        "confidence_level",
        "minimum_point_success_rate",
        "minimum_independent_raters",
        "minimum_rater_agreement",
        "tie_break_protocol_version",
        "minimum_runs",
    }
)
_CASE_KEYS = frozenset(
    {
        "case_id",
        "conversation_id",
        "turn_index",
        "locale",
        "content_commitment",
        "label_commitment",
        "tags",
        "rubric_item_ids",
    }
)


def load_manifest(path: Path) -> HiddenCorpusManifest:
    """Load and validate a manifest without reading the restricted corpus."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorpusManifestError("hidden corpus manifest is unreadable") from exc
    return parse_manifest(raw)


def parse_manifest(raw: object) -> HiddenCorpusManifest:
    root = _mapping(raw, "manifest")
    _exact_keys(root, _ROOT_KEYS, "manifest")
    if _integer(root["schema_version"], "schema_version") != 1:
        raise CorpusManifestError("schema_version MUST be 1")
    cases_raw = _array(root["cases"], "cases")
    return HiddenCorpusManifest(
        corpus_id=_string(root["corpus_id"], "corpus_id"),
        corpus_version=_string(root["corpus_version"], "corpus_version"),
        frozen_at=_string(root["frozen_at"], "frozen_at"),
        freeze_revision=_string(root["freeze_revision"], "freeze_revision"),
        qualification_contract_version=_string(
            root["qualification_contract_version"],
            "qualification_contract_version",
        ),
        qualification_contract_digest=_string(
            root["qualification_contract_digest"],
            "qualification_contract_digest",
        ),
        restricted_artifact_id=_string(
            root["restricted_artifact_id"],
            "restricted_artifact_id",
        ),
        hidden_payload_digest=_string(
            root["hidden_payload_digest"],
            "hidden_payload_digest",
        ),
        review_protocol=_review_protocol(_mapping(root["review_protocol"], "review_protocol")),
        rubric_observation_floors=_rubric_floors(
            _mapping(root["rubric_observation_floors"], "rubric_observation_floors")
        ),
        cases=tuple(_case(value, index) for index, value in enumerate(cases_raw)),
    )


def _review_protocol(raw: Mapping[str, Any]) -> ReviewProtocol:
    _exact_keys(raw, _PROTOCOL_KEYS, "review_protocol")
    return ReviewProtocol(
        labeling_protocol_version=_string(
            raw["labeling_protocol_version"],
            "labeling_protocol_version",
        ),
        evaluator_set_version=_string(
            raw["evaluator_set_version"],
            "evaluator_set_version",
        ),
        run_configuration_version=_string(
            raw["run_configuration_version"],
            "run_configuration_version",
        ),
        confidence_method=_string(raw["confidence_method"], "confidence_method"),
        confidence_level=_number(raw["confidence_level"], "confidence_level"),
        minimum_point_success_rate=_number(
            raw["minimum_point_success_rate"],
            "minimum_point_success_rate",
        ),
        minimum_independent_raters=_integer(
            raw["minimum_independent_raters"],
            "minimum_independent_raters",
        ),
        minimum_rater_agreement=_number(
            raw["minimum_rater_agreement"],
            "minimum_rater_agreement",
        ),
        tie_break_protocol_version=_string(
            raw["tie_break_protocol_version"],
            "tie_break_protocol_version",
        ),
        minimum_runs=_integer(raw["minimum_runs"], "minimum_runs"),
    )


def _rubric_floors(raw: Mapping[str, Any]) -> tuple[int, ...]:
    expected = {str(item_id) for item_id in range(1, 51)}
    if set(raw) != expected:
        raise CorpusManifestError("rubric_observation_floors MUST define item ids 1 through 50")
    return tuple(
        _integer(raw[str(item_id)], f"rubric_observation_floors.{item_id}")
        for item_id in range(1, 51)
    )


def _case(raw: object, index: int) -> HiddenCorpusCase:
    field = f"cases[{index}]"
    value = _mapping(raw, field)
    _exact_keys(value, _CASE_KEYS, field)
    tags = tuple(
        _coverage_tag(tag, f"{field}.tags") for tag in _array(value["tags"], f"{field}.tags")
    )
    item_ids = tuple(
        _integer(item_id, f"{field}.rubric_item_ids")
        for item_id in _array(
            value["rubric_item_ids"],
            f"{field}.rubric_item_ids",
        )
    )
    return HiddenCorpusCase(
        case_id=_string(value["case_id"], f"{field}.case_id"),
        conversation_id=_string(
            value["conversation_id"],
            f"{field}.conversation_id",
        ),
        turn_index=_integer(value["turn_index"], f"{field}.turn_index"),
        locale=_locale(value["locale"], f"{field}.locale"),
        content_commitment=_string(
            value["content_commitment"],
            f"{field}.content_commitment",
        ),
        label_commitment=_string(
            value["label_commitment"],
            f"{field}.label_commitment",
        ),
        tags=tags,
        rubric_item_ids=item_ids,
    )


def _mapping(raw: object, field: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise CorpusManifestError(f"{field} MUST be an object with string keys")
    return raw


def _array(raw: object, field: str) -> list[object]:
    if not isinstance(raw, list):
        raise CorpusManifestError(f"{field} MUST be an array")
    return raw


def _exact_keys(raw: Mapping[str, Any], expected: frozenset[str], field: str) -> None:
    actual = frozenset(raw)
    if actual != expected:
        raise CorpusManifestError(
            f"{field} fields differ: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


def _string(raw: object, field: str) -> str:
    if not isinstance(raw, str):
        raise CorpusManifestError(f"{field} MUST be a string")
    return raw


def _integer(raw: object, field: str) -> int:
    if type(raw) is not int:
        raise CorpusManifestError(f"{field} MUST be an integer")
    return raw


def _number(raw: object, field: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise CorpusManifestError(f"{field} MUST be a number")
    value = float(raw)
    if not math.isfinite(value):
        raise CorpusManifestError(f"{field} MUST be finite")
    return value


def _locale(raw: object, field: str) -> Locale:
    try:
        return Locale(_string(raw, field))
    except ValueError as exc:
        raise CorpusManifestError(f"{field} MUST be en or ko") from exc


def _coverage_tag(raw: object, field: str) -> CoverageTag:
    try:
        return CoverageTag(_string(raw, field))
    except ValueError as exc:
        raise CorpusManifestError(f"{field} contains an unsupported tag") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
    except CorpusManifestError as exc:
        print(f"chatops-quality-corpus-manifest: FAIL {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary(manifest), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
