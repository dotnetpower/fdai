from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from fdai.core.conversation_assurance.quality_latency import (
    CHATOPS_LATENCY_CONTRACT_V1,
)
from scripts.evaluation.chatops_quality_latency import main, parse_batch

_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "evaluation" / "chatops_quality_latency.py"
)


def _raw() -> dict[str, Any]:
    samples: list[dict[str, object]] = []
    index = 0
    for slo in CHATOPS_LATENCY_CONTRACT_V1.stages:
        for _ in range(slo.minimum_samples):
            samples.append(
                {
                    "stage": slo.stage.value,
                    "environment": slo.environment.value,
                    "observed_at": "2026-08-28T00:00:00Z",
                    "duration_ms": slo.p50_ceiling_ms,
                    "timestamp_authority": "stage-owner-clock",
                    "trace_digest": f"{index:064x}",
                    "provenance_digest": f"{index + 10_000:064x}",
                    "outcome": "completed",
                }
            )
            index += 1
    return {
        "schema_version": 1,
        "run_id": "latency-run-001",
        "source_revision": "a" * 40,
        "started_at": "2026-08-28T00:00:00Z",
        "completed_at": "2026-08-28T00:10:00Z",
        "samples": samples,
    }


def test_cli_emits_schema_valid_content_free_latency_evidence(tmp_path: Path) -> None:
    source = tmp_path / "samples.json"
    output = tmp_path / "evidence.json"
    source.write_text(json.dumps(_raw()), encoding="utf-8")

    assert main(["--input", str(source), "--output", str(output), "--require-slo"]) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["evidence_kind"] == "chatops_latency_benchmark"
    assert payload["latency_slo_met"] is True
    assert len(payload["stages"]) == 5
    assert all(stage["p99_ms"] is not None for stage in payload["stages"])
    assert all(
        stage["timestamp_authorities"] == ["stage-owner-clock"] for stage in payload["stages"]
    )
    rendered = json.dumps(payload)
    assert "latency-run-001" not in rendered
    assert "trace_digest" not in rendered
    assert "provenance_digest" not in rendered


def test_cli_requires_exact_content_free_schema(tmp_path: Path) -> None:
    raw = _raw()
    raw["samples"][0]["answer_text"] = "not allowed"

    try:
        parse_batch(raw)
    except ValueError as exc:
        assert "fields differ" in str(exc)
    else:
        raise AssertionError("identity or content fields must not be accepted")


def test_require_slo_returns_nonzero_and_retains_failed_evidence(tmp_path: Path) -> None:
    raw = _raw()
    raw["samples"] = [
        sample for sample in raw["samples"] if sample["stage"] != "channel_acknowledgement"
    ]
    source = tmp_path / "samples.json"
    output = tmp_path / "evidence.json"
    source.write_text(json.dumps(raw), encoding="utf-8")

    assert main(["--input", str(source), "--output", str(output), "--require-slo"]) == 1

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["latency_slo_met"] is False
    acknowledgement = payload["stages"][3]
    assert acknowledgement["sample_count"] == 0
    assert acknowledgement["passed"] is False


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
    assert "--require-slo" in completed.stdout
