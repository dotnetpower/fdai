"""Frozen-corpus run aggregation and scorecard regeneration tests."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    QualityDimension,
    QualityHardCap,
    QualityItemMeasurement,
)
from fdai.core.conversation_assurance.scorecard_cli import (
    ScorecardInputError,
    build_scorecard_from_document,
)
from fdai.core.conversation_assurance.scorecard_cli import main as scorecard_main
from fdai.core.conversation_assurance.scorecard_run import (
    SCORECARD_SCHEMA_VERSION,
    QualityRunEvidence,
    ScorecardBlocker,
    ScorecardProvenance,
    build_quality_scorecard,
)

_CONTRACT = CHATOPS_QUALITY_CONTRACT_V1


def _measurements(
    value: float,
    *,
    overrides: dict[int, float] | None = None,
    caps: dict[int, tuple[QualityHardCap, ...]] | None = None,
) -> tuple[QualityItemMeasurement, ...]:
    overrides = overrides or {}
    caps = caps or {}
    return tuple(
        QualityItemMeasurement(
            item_id=item.item_id,
            components=tuple(
                (dimension, overrides.get(item.item_id, value)) for dimension in QualityDimension
            ),
            triggered_caps=caps.get(item.item_id, ()),
        )
        for item in _CONTRACT.items
    )


def _run(
    run_id: str,
    *,
    value: float = 0.99,
    english: int = 250,
    korean: int = 250,
    overrides: dict[int, float] | None = None,
    caps: dict[int, tuple[QualityHardCap, ...]] | None = None,
) -> QualityRunEvidence:
    return QualityRunEvidence(
        run_id=run_id,
        english_turns=english,
        korean_turns=korean,
        measurements=_measurements(value, overrides=overrides, caps=caps),
    )


def _provenance() -> ScorecardProvenance:
    return ScorecardProvenance(
        contract_digest=_CONTRACT.content_digest,
        corpus_version="chatops-corpus-v1",
        corpus_digest="0" * 64,
        model_deployment_id="declared-deployment-id",
        evaluator_version="evaluator-v1",
        generated_by="scorecard_cli",
    )


def _three_runs() -> tuple[QualityRunEvidence, ...]:
    return (_run("run-1"), _run("run-2"), _run("run-3"))


def test_three_complete_runs_at_the_floors_qualify() -> None:
    scorecard = build_quality_scorecard(_three_runs(), contract=_CONTRACT, provenance=_provenance())

    assert scorecard.schema_version == SCORECARD_SCHEMA_VERSION
    assert scorecard.contract_version == "chatops-quality-v1"
    assert scorecard.run_ids == ("run-1", "run-2", "run-3")
    assert scorecard.minimum_english_turns == 250
    assert scorecard.minimum_korean_turns == 250
    assert len(scorecard.items) == 50
    assert all(item.passed for item in scorecard.items)
    assert scorecard.blockers == ()
    assert scorecard.qualified is True


def test_worst_run_decides_each_item_score() -> None:
    runs = (_run("run-1"), _run("run-2", overrides={7: 0.90}), _run("run-3"))

    scorecard = build_quality_scorecard(runs, contract=_CONTRACT, provenance=_provenance())

    item = scorecard.items[6]
    assert item.item_id == 7
    assert item.worst_run_id == "run-2"
    assert item.worst_score == pytest.approx(9.0)
    assert item.passed is False
    assert scorecard.blockers == (ScorecardBlocker.ITEM_BELOW_MINIMUM,)
    assert scorecard.qualified is False


def test_triggered_cap_is_retained_on_the_worst_run() -> None:
    runs = (
        _run("run-1"),
        _run("run-2", caps={3: (QualityHardCap.NO_PRODUCTION_E2E_EVIDENCE,)}),
        _run("run-3"),
    )

    scorecard = build_quality_scorecard(runs, contract=_CONTRACT, provenance=_provenance())

    item = scorecard.items[2]
    assert item.applied_caps == (QualityHardCap.NO_PRODUCTION_E2E_EVIDENCE,)
    assert item.worst_score == pytest.approx(9.4)
    assert item.passed is False


def test_two_runs_block_qualification() -> None:
    scorecard = build_quality_scorecard(
        (_run("run-1"), _run("run-2")), contract=_CONTRACT, provenance=_provenance()
    )

    assert ScorecardBlocker.INSUFFICIENT_RUNS in scorecard.blockers
    assert scorecard.qualified is False


def test_turn_and_locale_floors_block_qualification() -> None:
    runs = (_run("run-1"), _run("run-2", english=200, korean=260), _run("run-3"))

    scorecard = build_quality_scorecard(runs, contract=_CONTRACT, provenance=_provenance())

    assert ScorecardBlocker.CORPUS_TURN_FLOOR_UNMET in scorecard.blockers
    assert ScorecardBlocker.LOCALE_TURN_FLOOR_UNMET in scorecard.blockers
    assert scorecard.qualified is False


def test_one_locale_cannot_compensate_for_the_other() -> None:
    runs = (
        _run("run-1", english=500, korean=0),
        _run("run-2", english=500, korean=0),
        _run("run-3", english=500, korean=0),
    )

    scorecard = build_quality_scorecard(runs, contract=_CONTRACT, provenance=_provenance())

    assert scorecard.blockers == (ScorecardBlocker.LOCALE_TURN_FLOOR_UNMET,)
    assert scorecard.qualified is False


def test_stale_contract_digest_is_rejected() -> None:
    provenance = replace(_provenance(), contract_digest="f" * 64)

    with pytest.raises(ValueError, match="contract digest"):
        build_quality_scorecard(_three_runs(), contract=_CONTRACT, provenance=provenance)


def test_repeated_run_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        build_quality_scorecard(
            (_run("run-1"), _run("run-1"), _run("run-3")),
            contract=_CONTRACT,
            provenance=_provenance(),
        )


def test_empty_run_set_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one run"):
        build_quality_scorecard((), contract=_CONTRACT, provenance=_provenance())


def test_partial_run_is_rejected() -> None:
    partial = QualityRunEvidence(
        run_id="run-1",
        english_turns=250,
        korean_turns=250,
        measurements=_measurements(0.99)[:49],
    )

    with pytest.raises(ValueError, match="every contract item"):
        build_quality_scorecard((partial,), contract=_CONTRACT, provenance=_provenance())


def test_out_of_order_run_measurements_are_rejected() -> None:
    measurements = _measurements(0.99)

    with pytest.raises(ValueError, match="in id order"):
        QualityRunEvidence(
            run_id="run-1",
            english_turns=250,
            korean_turns=250,
            measurements=(measurements[1], measurements[0], *measurements[2:]),
        )


def test_negative_turn_counts_are_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        _run("run-1", english=-1)


def test_blank_provenance_field_is_rejected() -> None:
    with pytest.raises(ValueError, match="corpus_version"):
        replace(_provenance(), corpus_version="  ")


def _document() -> dict[str, object]:
    provenance = _provenance()
    return {
        "provenance": provenance.to_dict(),
        "runs": [
            {
                "run_id": run.run_id,
                "english_turns": run.english_turns,
                "korean_turns": run.korean_turns,
                "items": [
                    {
                        "id": measurement.item_id,
                        "components": {
                            dimension.value: value for dimension, value in measurement.components
                        },
                        "triggered_caps": [cap.value for cap in measurement.triggered_caps],
                    }
                    for measurement in run.measurements
                ],
            }
            for run in _three_runs()
        ],
    }


def test_document_reduction_matches_direct_aggregation() -> None:
    scorecard = build_scorecard_from_document(_document())

    assert scorecard.qualified is True
    assert (
        scorecard.content_digest
        == build_quality_scorecard(
            _three_runs(), contract=_CONTRACT, provenance=_provenance()
        ).content_digest
    )


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda document: document.pop("runs"), "runs MUST be an array"),
        (lambda document: document.pop("provenance"), "provenance MUST be an object"),
        (
            lambda document: document["runs"][0]["items"][0]["components"].pop(
                QualityDimension.LATENCY_AND_UX.value
            ),
            "latency_and_ux MUST be a number",
        ),
        (
            lambda document: document["runs"][0]["items"][0].update(
                {"triggered_caps": ["invented_cap"]}
            ),
            "unknown cap",
        ),
        (
            lambda document: document["runs"][0].update({"english_turns": "250"}),
            "english_turns MUST be an integer",
        ),
        (
            lambda document: document["provenance"].update({"contract_digest": "a" * 64}),
            "contract digest",
        ),
        (
            lambda document: document.update({"notes": "extra"}),
            r"document carries unsupported field\(s\): notes",
        ),
        (
            lambda document: document["provenance"].update({"judge_override": "approved"}),
            r"provenance carries unsupported field\(s\): judge_override",
        ),
        (
            lambda document: document["runs"][0].update({"english_turn": 250}),
            r"runs\[0\] carries unsupported field\(s\): english_turn",
        ),
        (
            lambda document: document["runs"][0]["items"][0].update({"trigered_caps": []}),
            r"items\[0\] carries unsupported field\(s\): trigered_caps",
        ),
        (
            lambda document: document["runs"][0]["items"][0]["components"].update(
                {"grounding": 1.0}
            ),
            r"components carries unsupported field\(s\): grounding",
        ),
    ],
)
def test_malformed_document_fails_closed(mutate: object, match: str) -> None:
    document = _document()
    mutate(document)  # type: ignore[operator]

    with pytest.raises(ScorecardInputError, match=match):
        build_scorecard_from_document(document)


def test_cli_regenerates_a_stable_artifact(tmp_path: Path) -> None:
    source = tmp_path / "measurements.json"
    source.write_text(json.dumps(_document()), encoding="utf-8")
    first = tmp_path / "scorecard-1.json"
    second = tmp_path / "scorecard-2.json"

    assert scorecard_main(["--input", str(source), "--output", str(first)]) == 0
    assert scorecard_main(["--input", str(source), "--output", str(second)]) == 0

    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
    artifact = json.loads(first.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == SCORECARD_SCHEMA_VERSION
    assert artifact["contract_version"] == "chatops-quality-v1"
    assert artifact["qualified"] is True
    assert len(artifact["items"]) == 50
    assert artifact["provenance"]["corpus_version"] == "chatops-corpus-v1"


def test_cli_reports_blocked_qualification_without_failing(tmp_path: Path) -> None:
    document = _document()
    document["runs"] = document["runs"][:2]  # type: ignore[index]
    source = tmp_path / "measurements.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    output = tmp_path / "scorecard.json"

    assert scorecard_main(["--input", str(source), "--output", str(output)]) == 0

    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["qualified"] is False
    assert artifact["blockers"] == [ScorecardBlocker.INSUFFICIENT_RUNS.value]


def test_cli_rejects_malformed_input(tmp_path: Path) -> None:
    source = tmp_path / "measurements.json"
    source.write_text("{", encoding="utf-8")

    assert scorecard_main(["--input", str(source)]) == 2


def test_cli_rejects_a_missing_input(tmp_path: Path) -> None:
    assert scorecard_main(["--input", str(tmp_path / "absent.json")]) == 2


def test_cli_rejects_a_symlinked_input(tmp_path: Path) -> None:
    real = tmp_path / "measurements.json"
    real.write_text(json.dumps(_document()), encoding="utf-8")
    link = tmp_path / "linked.json"
    link.symlink_to(real)

    assert scorecard_main(["--input", str(link)]) == 2


def test_cli_rejects_a_symlinked_output(tmp_path: Path) -> None:
    source = tmp_path / "measurements.json"
    source.write_text(json.dumps(_document()), encoding="utf-8")
    target = tmp_path / "target.json"
    target.write_text("", encoding="utf-8")
    link = tmp_path / "linked-scorecard.json"
    link.symlink_to(target)

    assert scorecard_main(["--input", str(source), "--output", str(link)]) == 2
    assert target.read_text(encoding="utf-8") == ""


def test_documented_module_command_regenerates_the_artifact(tmp_path: Path) -> None:
    source = tmp_path / "measurements.json"
    source.write_text(json.dumps(_document()), encoding="utf-8")
    output = tmp_path / "scorecard.json"

    completed = subprocess.run(  # noqa: S603 - fixed argv, interpreter from sys.executable
        [
            sys.executable,
            "-m",
            "fdai.core.conversation_assurance.scorecard_cli",
            "--input",
            str(source),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["qualified"] is True
