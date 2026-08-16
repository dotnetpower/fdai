"""Regenerate the ChatOps qualification scorecard from recorded measurements.

One documented command turns a recorded measurement file into the stable
scorecard artifact:

.. code-block:: shell

    uv run python -m fdai.core.conversation_assurance.scorecard_cli \\
        --input <measurements.json> --output <scorecard.json>

The CLI is a pure reducer. It reads recorded measurements, applies the
installed :data:`CHATOPS_QUALITY_CONTRACT_V1`, and writes the artifact. It
performs no model call, no provider call, and no measurement of its own, so
rerunning it on the same input reproduces byte-identical output.

Exit codes
----------

- ``0`` - the scorecard was produced. Qualification is reported inside the
  artifact; a blocked scorecard is still a successful regeneration.
- ``2`` - the input is unreadable, malformed, or inconsistent with the
  installed contract (fail fast, per ``coding-conventions.instructions.md``).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    QualityDimension,
    QualityHardCap,
    QualityItemMeasurement,
)
from fdai.core.conversation_assurance.scorecard_run import (
    QualityRunEvidence,
    QualityScorecard,
    ScorecardProvenance,
    build_quality_scorecard,
)

_MAX_INPUT_BYTES = 8_000_000


class ScorecardInputError(ValueError):
    """The recorded measurement document cannot be reduced as written."""


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ScorecardInputError(f"{field} MUST be an object")
    return value


def _require_sequence(value: Any, field: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ScorecardInputError(f"{field} MUST be an array")
    return value


def _require_str(container: Mapping[str, Any], field: str, parent: str) -> str:
    value = container.get(field)
    if not isinstance(value, str):
        raise ScorecardInputError(f"{parent}.{field} MUST be a string")
    return value


def _require_int(container: Mapping[str, Any], field: str, parent: str) -> int:
    value = container.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ScorecardInputError(f"{parent}.{field} MUST be an integer")
    return value


def _parse_components(value: Any, parent: str) -> tuple[tuple[QualityDimension, float], ...]:
    components = _require_mapping(value, f"{parent}.components")
    parsed: list[tuple[QualityDimension, float]] = []
    for dimension in QualityDimension:
        raw = components.get(dimension.value)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ScorecardInputError(f"{parent}.components.{dimension.value} MUST be a number")
        parsed.append((dimension, float(raw)))
    return tuple(parsed)


def _parse_caps(value: Any, parent: str) -> tuple[QualityHardCap, ...]:
    if value is None:
        return ()
    known = {cap.value: cap for cap in QualityHardCap}
    parsed: list[QualityHardCap] = []
    for entry in _require_sequence(value, f"{parent}.triggered_caps"):
        if not isinstance(entry, str) or entry not in known:
            raise ScorecardInputError(f"{parent}.triggered_caps names an unknown cap")
        parsed.append(known[entry])
    return tuple(parsed)


def _parse_measurement(value: Any, parent: str) -> QualityItemMeasurement:
    entry = _require_mapping(value, parent)
    return QualityItemMeasurement(
        item_id=_require_int(entry, "id", parent),
        components=_parse_components(entry.get("components"), parent),
        triggered_caps=_parse_caps(entry.get("triggered_caps"), parent),
    )


def _parse_run(value: Any, index: int) -> QualityRunEvidence:
    parent = f"runs[{index}]"
    run = _require_mapping(value, parent)
    measurements = tuple(
        _parse_measurement(entry, f"{parent}.items[{position}]")
        for position, entry in enumerate(_require_sequence(run.get("items"), f"{parent}.items"))
    )
    return QualityRunEvidence(
        run_id=_require_str(run, "run_id", parent),
        english_turns=_require_int(run, "english_turns", parent),
        korean_turns=_require_int(run, "korean_turns", parent),
        measurements=measurements,
    )


def build_scorecard_from_document(document: Any) -> QualityScorecard:
    """Reduce one recorded measurement document to a scorecard.

    Raises:
        ScorecardInputError: when the document shape, dimensions, caps, or
            declared contract digest cannot be reduced as written.
    """

    root = _require_mapping(document, "document")
    provenance_source = _require_mapping(root.get("provenance"), "provenance")
    provenance = ScorecardProvenance(
        contract_digest=_require_str(provenance_source, "contract_digest", "provenance"),
        corpus_version=_require_str(provenance_source, "corpus_version", "provenance"),
        corpus_digest=_require_str(provenance_source, "corpus_digest", "provenance"),
        model_deployment_id=_require_str(provenance_source, "model_deployment_id", "provenance"),
        evaluator_version=_require_str(provenance_source, "evaluator_version", "provenance"),
        generated_by=_require_str(provenance_source, "generated_by", "provenance"),
    )
    runs = tuple(
        _parse_run(entry, index)
        for index, entry in enumerate(_require_sequence(root.get("runs"), "runs"))
    )
    try:
        return build_quality_scorecard(
            runs,
            contract=CHATOPS_QUALITY_CONTRACT_V1,
            provenance=provenance,
        )
    except ValueError as error:
        raise ScorecardInputError(str(error)) from error


def _read_document(path: Path) -> Any:
    if path.is_symlink():
        raise ScorecardInputError("measurement input MUST NOT be a symlink")
    raw = path.read_bytes()
    if len(raw) > _MAX_INPUT_BYTES:
        raise ScorecardInputError("measurement input exceeds the supported size")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ScorecardInputError(f"measurement input is not valid JSON: {error}") from error


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chatops-quality-scorecard",
        description="Regenerate the ChatOps qualification scorecard from recorded measurements.",
    )
    parser.add_argument("--input", required=True, type=Path, help="recorded measurement JSON file")
    parser.add_argument("--output", type=Path, help="scorecard artifact path; defaults to stdout")
    arguments = parser.parse_args(argv)

    try:
        scorecard = build_scorecard_from_document(_read_document(arguments.input))
    except (ScorecardInputError, OSError) as error:
        print(f"chatops-quality-scorecard: ERROR: {error}", file=sys.stderr)
        return 2

    rendered = f"{scorecard.to_json()}\n"
    if arguments.output is None:
        sys.stdout.write(rendered)
    else:
        arguments.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
