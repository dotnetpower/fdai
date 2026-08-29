from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    QualityDimension,
)

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "evaluation"
    / "chatops-quality-qualification.py"
)


@pytest.fixture(scope="module")
def module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("chatops_quality_qualification_cli", _SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _payload(*, run_count: int = 3, turn_count: int = 500) -> dict[str, object]:
    contract = CHATOPS_QUALITY_CONTRACT_V1
    per_locale = turn_count // 2
    components = {dimension.value: 0.98 for dimension in QualityDimension}
    evidence = {
        "frozen_blind_corpus": True,
        "production_e2e": True,
        "latency_slo": True,
        "complete_trace": True,
        "critical_safety_escape": False,
    }
    return {
        "schema_version": "1.0.0",
        "qualification_id": "qualification-v1",
        "provenance": {
            "source_revision": "b" * 40,
            "contract_version": contract.version,
            "contract_digest": contract.content_digest,
            "runner_version": "runner-v1",
            "evaluator_versions": ["deterministic-v1", "semantic-v1"],
            "model_identifiers": ["model-a", "model-b"],
            "deployment_identifiers": ["deployment-a"],
            "run_configuration_digest": "a" * 64,
        },
        "corpus": {
            "corpus_id": "chatops-hidden",
            "corpus_version": "v1",
            "content_digest": "c" * 64,
            "turn_count": turn_count,
            "english_turns": per_locale,
            "korean_turns": per_locale,
        },
        "runs": [
            {
                "run_id": f"run-{run_index}",
                "started_at": f"2026-08-2{run_index}T00:00:00Z",
                "completed_at": f"2026-08-2{run_index}T00:10:00Z",
                "items": [
                    {
                        "item_id": item_id,
                        "components": components,
                        "evidence": evidence,
                    }
                    for item_id in range(1, 51)
                ],
            }
            for run_index in range(1, run_count + 1)
        ],
    }


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_emits_stable_scorecard_but_fails_closed_without_verified_admission(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    source = tmp_path / "batch.json"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write(source, _payload())

    assert module.main(["--input", str(source), "--output", str(first), "--require-qualified"]) == 3
    assert module.main(["--input", str(source), "--output", str(second)]) == 0

    scorecard = json.loads(first.read_text())
    assert first.read_bytes() == second.read_bytes()
    assert scorecard["qualified"] is False
    assert scorecard["gaps"] == ["decision_evidence_admission_missing"]
    assert scorecard["qualification_authority"] is False
    assert scorecard["decision_evidence_receipt_digest"] is None
    assert scorecard["decision_evidence_verification_bundle_digest"] is None
    assert len(scorecard["items"]) == 50
    assert len(scorecard["content_digest"]) == 64


def test_incomplete_batch_is_retained_but_fails_require_qualified(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    source = tmp_path / "batch.json"
    output = tmp_path / "scorecard.json"
    _write(source, _payload(run_count=2))

    assert (
        module.main(["--input", str(source), "--output", str(output), "--require-qualified"]) == 3
    )
    assert json.loads(output.read_text())["gaps"] == [
        "run_count=2<minimum_runs=3",
        "decision_evidence_admission_missing",
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update({"unexpected": True}),
        lambda payload: payload["runs"][0]["items"][0]["components"].update(
            {"functional_correctness": True}
        ),
        lambda payload: payload["runs"][0]["items"].pop(),
        lambda payload: payload["provenance"].update({"contract_digest": "d" * 64}),
    ],
)
def test_malformed_widened_or_mismatched_input_fails_closed(
    module: ModuleType,
    tmp_path: Path,
    mutation: object,
) -> None:
    source = tmp_path / "batch.json"
    payload = _payload()
    mutation(payload)  # type: ignore[operator]
    _write(source, payload)

    assert module.main(["--input", str(source)]) == 2


def test_direct_script_entrypoint_is_runnable() -> None:
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        (sys.executable, str(_SCRIPT), "--help"),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0
    assert "--input" in completed.stdout
