from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "evaluation"
    / "answer-planning-qualification.py"
)


@pytest.fixture(scope="module")
def module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("answer_planning_qualification_cli", _SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _batch(sample_count: int = 100) -> dict[str, object]:
    return {
        "scenario_set_version": "answer-planning-v1",
        "runner_version": "measured-runner-v1",
        "samples": [
            {
                "case_id": f"case-{index:03d}",
                "locale": "en" if index < 50 else "ko",
                "baseline_unique_evidence_count": 0,
                "candidate_unique_evidence_count": 1,
                "baseline_correction_required": index % 10 == 0,
                "candidate_correction_required": False,
                "baseline_follow_up_required": index % 5 == 0,
                "candidate_follow_up_required": index % 10 == 0,
                "unsupported_claim_escape": False,
                "authority_violation": False,
                "clean_answer_regression": False,
                "planning_elapsed_ms": 900,
                "added_tokens": 400,
            }
            for index in range(sample_count)
        ],
    }


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_measured_batch_emits_stable_no_authority_receipt(
    module: ModuleType, tmp_path: Path
) -> None:
    source = tmp_path / "batch.json"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write(source, _batch())

    assert module.main(["--input", str(source), "--output", str(first), "--require-ready"]) == 0
    assert module.main(["--input", str(source), "--output", str(second)]) == 0

    receipt = json.loads(first.read_text())
    assert first.read_bytes() == second.read_bytes()
    assert receipt["ready_for_review"] is True
    assert receipt["activation_authority"] is False
    assert receipt["english_samples"] == receipt["korean_samples"] == 50
    assert len(receipt["evidence_digest"]) == 64


def test_incomplete_batch_fails_require_ready(module: ModuleType, tmp_path: Path) -> None:
    source = tmp_path / "batch.json"
    output = tmp_path / "receipt.json"
    _write(source, _batch(10))

    assert module.main(["--input", str(source), "--output", str(output), "--require-ready"]) == 3

    receipt = json.loads(output.read_text())
    assert receipt["ready_for_review"] is False
    assert receipt["activation_authority"] is False
    assert receipt["gaps"] == [
        "sample_count=10<min_samples=100",
        "english_samples=10<min_samples_per_locale=50",
        "korean_samples=0<min_samples_per_locale=50",
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update({"unexpected": True}),
        lambda payload: payload["samples"][0].update({"added_tokens": True}),
        lambda payload: payload["samples"][0].update({"locale": "fr"}),
    ],
)
def test_malformed_or_widened_input_fails_closed(
    module: ModuleType, tmp_path: Path, mutation: object
) -> None:
    source = tmp_path / "batch.json"
    payload = _batch()
    mutation(payload)  # type: ignore[operator]
    _write(source, payload)

    assert module.main(["--input", str(source)]) == 2
