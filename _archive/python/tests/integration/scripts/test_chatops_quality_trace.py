from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from fdai.core.conversation_assurance.quality_trace import CorrelationTraceStage
from scripts.evaluation.chatops_quality_trace import main, parse_batch

_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "evaluation" / "chatops_quality_trace.py"
)


def _raw() -> dict[str, Any]:
    events: list[dict[str, object]] = []
    predecessor = None
    for index, stage in enumerate(CorrelationTraceStage):
        record_digest = f"{index + 1:064x}"
        events.append(
            {
                "stage": stage.value,
                "occurred_at": f"2026-08-28T00:00:{index:02d}Z",
                "timestamp_authority": (
                    "provider_receipt"
                    if stage is CorrelationTraceStage.DELIVERY
                    else "database_commit"
                ),
                "correlation_digest": "a" * 64,
                "record_digest": record_digest,
                "predecessor_record_digest": predecessor,
                "provenance_digest": f"{index + 100:064x}",
            }
        )
        predecessor = record_digest
    return {
        "schema_version": 1,
        "trace_id": "trace-001",
        "source_revision": "b" * 40,
        "started_at": "2026-08-28T00:00:00Z",
        "completed_at": "2026-08-28T00:01:00Z",
        "events": events,
    }


def test_cli_emits_complete_content_free_trace(tmp_path: Path) -> None:
    source = tmp_path / "trace.json"
    output = tmp_path / "evidence.json"
    source.write_text(json.dumps(_raw()), encoding="utf-8")

    assert main(["--input", str(source), "--output", str(output), "--require-complete"]) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["complete_trace"] is True
    assert set(payload["stage_counts"]) == {stage.value for stage in CorrelationTraceStage}
    rendered = json.dumps(payload)
    assert "trace-001" not in rendered
    assert "record_digest" not in rendered
    assert "provenance_digest" not in rendered


def test_require_complete_returns_nonzero_with_retained_gaps(tmp_path: Path) -> None:
    raw = _raw()
    raw["events"].pop()
    source = tmp_path / "trace.json"
    output = tmp_path / "evidence.json"
    source.write_text(json.dumps(raw), encoding="utf-8")

    assert main(["--input", str(source), "--output", str(output), "--require-complete"]) == 1

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["complete_trace"] is False
    assert payload["gaps"]


def test_cli_rejects_identity_or_content_fields() -> None:
    raw = _raw()
    raw["events"][0]["principal_id"] = "not-allowed"

    try:
        parse_batch(raw)
    except ValueError as exc:
        assert "fields differ" in str(exc)
    else:
        raise AssertionError("identity or content fields must not be accepted")


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
    assert "--require-complete" in completed.stdout
