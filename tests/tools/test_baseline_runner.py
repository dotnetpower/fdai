"""Baseline runner + reference-agent smoke tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from tools.baseline_run import _run
from tools.reference_agent import AgentDecision, ReferenceAgent

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = REPO_ROOT / "tests" / "scenarios" / "v2026.07"


def test_reference_agent_is_deterministic() -> None:
    """Two invocations of the reference agent yield byte-identical outputs."""
    agent_a = ReferenceAgent()
    agent_b = ReferenceAgent()
    event = {
        "schema_version": "1.0.0",
        "event_id": "00000000-0000-0000-0000-000000000001",
        "source": "example_source",
        "event_type": "change_detected",
    }
    a = agent_a.decide(event)
    b = agent_b.decide(event)
    assert a == b
    assert isinstance(a, AgentDecision)
    assert a.decision == "hil"


def test_run_produces_the_expected_summary_shape() -> None:
    _, summary = _run(SCENARIOS)
    assert summary["scenario_count"] == 9
    assert summary["reference_agent"] == ReferenceAgent.VERSION
    assert "success_metrics" in summary
    assert "guard_metrics_baseline" in summary
    assert "per_domain" in summary
    assert set(summary["per_domain"]) == {"change", "dr", "finops"}
    # Stub always routes to HIL → auto rate is 0.
    assert summary["success_metrics"]["auto_resolution_rate"] == 0.0
    assert summary["success_metrics"]["hil_rate"] == 1.0


def test_run_is_reproducible() -> None:
    """Same scenario version + same agent version → same summary."""
    _, first = _run(SCENARIOS)
    _, second = _run(SCENARIOS)
    # `generated_at` timestamps differ between runs; every other key MUST match.
    first_copy = dict(first)
    second_copy = dict(second)
    del first_copy["generated_at"]
    del second_copy["generated_at"]
    assert first_copy == second_copy


def test_measured_observations_are_marked_but_small_sample_is_not_claim_eligible(
    tmp_path: Path,
) -> None:
    scenarios = [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(SCENARIOS.glob("*.json"))
    ]
    observations = {
        "reference_agent": "reference-observation@example",
        "scenario_set_version": "v2026.07",
        "outcomes": [
            {
                "scenario_id": scenario["id"],
                "predicted_tier": scenario["expected"]["tier"],
                "predicted_decision": scenario["expected"]["decision"],
                "executed": False,
                "rolled_back": False,
                "policy_violation": False,
                "latency_ms": 10.0,
                "model_calls": 1 if scenario["expected"]["tier"] == "t2" else 0,
                "input_tokens": 100 if scenario["expected"]["tier"] == "t2" else 0,
                "output_tokens": 20 if scenario["expected"]["tier"] == "t2" else 0,
                "cost_usd": 0.01 if scenario["expected"]["tier"] == "t2" else 0.0,
                "verifier_outcome": (
                    "eligible" if scenario["expected"]["tier"] == "t2" else "not_invoked"
                ),
            }
            for scenario in scenarios
        ],
    }
    path = tmp_path / "observations.json"
    path.write_text(json.dumps(observations), encoding="utf-8")

    _, summary = _run(SCENARIOS, path)

    assert summary["evidence"]["kind"] == "measured-observations"
    assert summary["evidence"]["claim_eligible"] is False
    assert summary["confidence_intervals_95"]["routed_correctly_rate"]["sample_size"] == 9
    assert summary["tier_economics"]["t2"]["model_calls"] == 1
    assert summary["model_economics"]["cost_usd"] == 0.01
    assert summary["quality_evidence"]["verifier_failure_count"] == 0
    assert summary["release_gate"]["checks"]["minimum_sample_size"] is False


def test_cli_writes_report_and_json(tmp_path: Path) -> None:
    """`python -m tools.baseline_run` runs green and produces both artifacts."""
    report = tmp_path / "report.md"
    payload = tmp_path / "summary.json"

    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [
            sys.executable,
            "-m",
            "tools.baseline_run",
            "--scenarios",
            str(SCENARIOS),
            "--json",
            str(payload),
            "--report",
            str(report),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert report.exists()
    assert payload.exists()
    assert "unmeasured" in report.read_text(encoding="utf-8")

    parsed = json.loads(payload.read_text(encoding="utf-8"))
    assert parsed["scenario_count"] == 9

    # The KO sibling MUST have been emitted alongside the EN report.
    ko_sibling = report.with_name(report.stem + "-ko" + report.suffix)
    assert ko_sibling.exists()

    report_bytes = report.read_bytes()
    ko_text = ko_sibling.read_text(encoding="utf-8")
    assert report_bytes.endswith(b"\n") and not report_bytes.endswith(b"\n\n")
    assert ko_text.endswith("\n") and not ko_text.endswith("\n\n")

    recorded_sha = next(
        line.removeprefix("translation_source_sha: ")
        for line in ko_text.splitlines()
        if line.startswith("translation_source_sha: ")
    )
    expected_sha = hashlib.sha1(  # noqa: S324 - verifies Git blob compatibility
        b"blob " + str(len(report_bytes)).encode() + b"\x00" + report_bytes,
        usedforsecurity=False,
    ).hexdigest()
    assert recorded_sha == expected_sha


def test_release_gate_blocks_incomplete_small_baseline() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [
            sys.executable,
            "-m",
            "tools.baseline_run",
            "--scenarios",
            str(SCENARIOS),
            "--require-release-eligible",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 3
    assert json.loads(result.stdout)["release_gate"]["release_eligible"] is False


def test_measured_observations_require_economics_fields(tmp_path: Path) -> None:
    scenarios = [json.loads(path.read_text()) for path in sorted(SCENARIOS.glob("*.json"))]
    path = tmp_path / "observations.json"
    path.write_text(
        json.dumps(
            {
                "reference_agent": "incomplete-observation@example",
                "scenario_set_version": "v2026.07",
                "outcomes": [
                    {
                        "scenario_id": scenario["id"],
                        "predicted_tier": "t0",
                        "predicted_decision": "hil",
                        "executed": False,
                        "rolled_back": False,
                        "policy_violation": False,
                    }
                    for scenario in scenarios
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="latency_ms"):
        _run(SCENARIOS, path)


def test_committed_baseline_artifact_matches_a_fresh_run() -> None:
    """W3.4 reproducibility CI gate.

    The shipped `docs/baselines/v2026.07.json` MUST remain reproducible from
    the pinned reference agent + frozen scenario set. If a fresh run diverges
    on anything other than the wall-clock ``generated_at`` field, the
    baseline artifact is stale and has to be regenerated (or the pinned agent
    version bumped) in the same PR that caused the drift.

    This is stricter than the CI-band variant described in
    docs/roadmap/phases/phase-0-instrumentation.md § W3.4 because the
    reference agent is deterministic; we get byte-exact reproducibility, not
    a confidence interval.
    """
    committed = json.loads(
        (REPO_ROOT / "docs" / "baselines" / "v2026.07.json").read_text(encoding="utf-8")
    )
    _, fresh = _run(SCENARIOS)

    committed_copy = dict(committed)
    fresh_copy = dict(fresh)
    del committed_copy["generated_at"]
    del fresh_copy["generated_at"]

    assert committed_copy == fresh_copy, (
        "committed docs/baselines/v2026.07.json diverges from a fresh run - "
        "regenerate with `python -m tools.baseline_run --scenarios "
        "tests/scenarios/v2026.07 --json docs/baselines/v2026.07.json "
        "--report docs/baselines/v2026.07.md` or bump the reference-agent "
        "version pin"
    )
