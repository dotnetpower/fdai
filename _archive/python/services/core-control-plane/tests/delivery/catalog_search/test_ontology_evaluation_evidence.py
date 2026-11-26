"""Retain real execution reports before proceeding, without external model calls."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from fdai.delivery.catalog_search import ontology_evaluation_evidence as evidence_module
from fdai.delivery.catalog_search.ontology_evaluation_evidence import (
    OntologyEvaluationEvidence,
    OntologyEvaluationEvidenceError,
)
from fdai.delivery.catalog_search.ontology_evaluation_execution import (
    OntologyRetrievalExecutionAbortedError,
    OntologyRetrievalExecutionReport,
)
from fdai.delivery.catalog_search.ontology_evaluation_runner import (
    OntologyRetrievalEvaluationReport,
)
from pydantic import TypeAdapter
from tests.delivery.catalog_search.test_ontology_evaluation_execution import (
    _BoundEmbedder,
    _execute,
)
from tests.delivery.catalog_search.test_ontology_evaluation_runner import _harness


def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_bytes().splitlines()]


@pytest.mark.parametrize("passed", [True, False])
async def test_persists_json_reports_before_holdout_and_returns_exact_result(
    tmp_path: Path, passed: bool
) -> None:
    path = tmp_path / "attempt.jsonl"
    harness, embedder = await _harness(), _BoundEmbedder()
    embedder.wrong = not passed
    with OntologyEvaluationEvidence(path, source_commit="a" * 40) as evidence:
        result = await _execute(harness, embedder, evidence=evidence)
    records = _records(path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert [record["sequence"] for record in records] == list(range(len(records)))
    assert all(record["recorded_at"].endswith("Z") for record in records)
    assert all(record["production_qualification"] is False for record in records)
    assert all(record["execution_authority"] is False for record in records)
    assert all(record["source_commit"] == "a" * 40 for record in records)
    assert records[0]["event"] == "started"
    assert records[0]["payload"]["plan"]["binding_digest"] == result.campaign.binding_digest
    stages = [record for record in records if record["event"] == "stage"]
    assert len(stages) == (2 if passed else 1)
    calibration = TypeAdapter(OntologyRetrievalEvaluationReport).validate_python(
        stages[0]["payload"]["report"]
    )
    assert calibration == result.campaign.calibration
    assert stages[0]["payload"]["report_digest"] == calibration.digest
    calls = [
        record["payload"]["call_index"]
        for record in records
        if record["event"] == "embedding_call_intent"
    ]
    assert calls == list(range(1, result.embedding_calls + 1))
    calibration_index = records.index(stages[0])
    assert records[calibration_index - 1]["payload"]["call_index"] == 12
    if passed:
        assert records[calibration_index + 1]["payload"]["call_index"] == 13
    else:
        assert result.campaign.holdout is None
    terminal = records[-1]
    assert terminal["event"] == "completed"
    assert (
        TypeAdapter(OntologyRetrievalExecutionReport).validate_python(terminal["payload"]["report"])
        == result
    )
    assert terminal["payload"]["campaign_digest"] == result.campaign.digest


@pytest.mark.parametrize("destination", ["existing", "symlink", "directory", "missing-parent"])
async def test_refuses_unavailable_output_before_dispatch(tmp_path: Path, destination: str) -> None:
    path = tmp_path / "attempt.jsonl"
    previous = tmp_path / "previous.jsonl"
    previous.write_bytes(b"original")
    if destination == "existing":
        path.write_bytes(b"original")
    elif destination == "symlink":
        path.symlink_to(previous)
    elif destination == "directory":
        path.mkdir()
    else:
        path = tmp_path / "missing" / "attempt.jsonl"
    harness, embedder = await _harness(), _BoundEmbedder()
    with pytest.raises(OntologyEvaluationEvidenceError, match="new writable"):
        with OntologyEvaluationEvidence(path) as evidence:
            await _execute(harness, embedder, evidence=evidence)
    assert embedder.calls == 0
    assert previous.read_bytes() == b"original"
    if destination == "existing":
        assert path.read_bytes() == b"original"


@pytest.mark.parametrize(
    ("event", "expected_calls"),
    [("started", 0), ("embedding_call_intent", 1), ("stage", 12), ("completed", 32)],
)
async def test_storage_failure_stops_at_exact_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event: str, expected_calls: int
) -> None:
    path = tmp_path / "attempt.jsonl"
    harness, embedder = await _harness(), _BoundEmbedder()
    original_write = os.write

    def fail_write(descriptor: int, data: memoryview) -> int:
        record = json.loads(bytes(data))
        if record["event"] == event and (
            event != "embedding_call_intent" or record["payload"]["call_index"] == 2
        ):
            raise OSError("private storage failure detail")
        return original_write(descriptor, data)

    monkeypatch.setattr(evidence_module.os, "write", fail_write)
    with OntologyEvaluationEvidence(path) as evidence:
        with pytest.raises(OntologyEvaluationEvidenceError) as failure:
            await _execute(harness, embedder, evidence=evidence)
    assert embedder.calls == expected_calls
    assert "private storage" not in str(failure.value)
    assert "completed" not in [record["event"] for record in _records(path)]
    if event == "completed":
        assert len([record for record in _records(path) if record["event"] == "stage"]) == 2


@pytest.mark.parametrize("fail_at", [1, 14])
async def test_provider_abort_retains_partial_evidence_without_error_text(
    tmp_path: Path, fail_at: int
) -> None:
    path = tmp_path / "attempt.jsonl"
    harness, embedder = await _harness(), _BoundEmbedder()
    embedder.fail_on_call = fail_at
    with OntologyEvaluationEvidence(path) as evidence:
        with pytest.raises(OntologyRetrievalExecutionAbortedError) as failure:
            await _execute(harness, embedder, evidence=evidence)
    records = _records(path)
    terminal = records[-1]
    assert terminal["event"] == "aborted"
    assert terminal["payload"]["embedding_calls"] == failure.value.embedding_calls == fail_at
    assert "private-provider-error" not in path.read_text()
    if fail_at == 14:
        calibration = TypeAdapter(OntologyRetrievalEvaluationReport).validate_python(
            terminal["payload"]["calibration"]
        )
        assert calibration.passed
        assert len(terminal["payload"]["completed"]) == 1


@pytest.mark.parametrize("persistence_fails", [False, True])
async def test_cancellation_propagates_even_if_its_receipt_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, persistence_fails: bool
) -> None:
    path = tmp_path / "attempt.jsonl"
    harness, embedder = await _harness(), _BoundEmbedder()
    embedder.stall = True
    original_write = os.write

    def fail_cancel(descriptor: int, data: memoryview) -> int:
        if persistence_fails and json.loads(bytes(data))["event"] == "cancelled":
            raise OSError("private cancellation write detail")
        return original_write(descriptor, data)

    monkeypatch.setattr(evidence_module.os, "write", fail_cancel)
    with OntologyEvaluationEvidence(path) as evidence:
        task = asyncio.create_task(_execute(harness, embedder, evidence=evidence))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await task
    assert embedder.calls == 1
    if persistence_fails:
        assert isinstance(cancelled.value.__cause__, OntologyEvaluationEvidenceError)
        assert _records(path)[-1]["event"] == "embedding_call_intent"
    else:
        assert _records(path)[-1]["event"] == "cancelled"


@pytest.mark.parametrize("failure", ["serialization", "fsync", "zero-write", "oversize"])
def test_writer_fails_explicitly_and_never_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    path = tmp_path / "attempt.jsonl"
    with OntologyEvaluationEvidence(path) as evidence:
        payload: dict[str, Any] = {}
        if failure == "serialization":
            payload["unsupported"] = object()
        elif failure == "fsync":

            def fail_sync(descriptor: int) -> None:
                raise OSError("private storage detail")

            monkeypatch.setattr(evidence_module.os, "fsync", fail_sync)
        elif failure == "zero-write":
            monkeypatch.setattr(evidence_module.os, "write", lambda *_: 0)
        else:
            monkeypatch.setattr(evidence_module, "_MAX_RECORD_BYTES", 1)
        with pytest.raises(OntologyEvaluationEvidenceError, match="could not be retained"):
            evidence.record("started", payload)
        prior = path.read_bytes()
        with pytest.raises(OntologyEvaluationEvidenceError, match="unavailable"):
            evidence.record("completed", {})
        assert path.read_bytes() == prior


def test_short_writes_are_completed_and_terminal_writer_is_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "attempt.jsonl"
    original_write = os.write
    monkeypatch.setattr(
        evidence_module.os, "write", lambda descriptor, data: original_write(descriptor, data[:7])
    )
    with OntologyEvaluationEvidence(path) as evidence:
        evidence.record("started", {})
        evidence.record("completed", {})
        with pytest.raises(OntologyEvaluationEvidenceError, match="unavailable"):
            evidence.record("started", {})
    assert [record["event"] for record in _records(path)] == ["started", "completed"]
    with pytest.raises(OntologyEvaluationEvidenceError, match="cannot be reused"):
        with evidence:
            pass


def test_partial_failed_append_preserves_earlier_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "attempt.jsonl"
    original_write = os.write
    written = False

    def partial_write(descriptor: int, data: memoryview) -> int:
        nonlocal written
        if written:
            raise OSError("interrupted write")
        written = True
        return original_write(descriptor, data[:10])

    with OntologyEvaluationEvidence(path) as evidence:
        evidence.record("started", {})
        prior = path.read_bytes()
        monkeypatch.setattr(evidence_module.os, "write", partial_write)
        with pytest.raises(OntologyEvaluationEvidenceError):
            evidence.record("completed", {})
        assert path.read_bytes().startswith(prior)
        assert not path.read_bytes().endswith(b"\n")
        assert json.loads(path.read_bytes().splitlines()[0])["event"] == "started"


@pytest.mark.parametrize("limit", ["bytes", "records"])
def test_attempt_recording_capacity_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    path = tmp_path / "attempt.jsonl"
    with OntologyEvaluationEvidence(path) as evidence:
        evidence.record("started", {})
        if limit == "bytes":
            monkeypatch.setattr(evidence_module, "_MAX_FILE_BYTES", path.stat().st_size)
        else:
            for index in range(133):
                evidence.record("embedding_call_intent", {"call_index": index + 1})
        prior = path.read_bytes()
        with pytest.raises(OntologyEvaluationEvidenceError):
            evidence.record("embedding_call_intent", {})
        assert path.read_bytes() == prior


@pytest.mark.parametrize("started", [True, False])
def test_rejects_missing_or_duplicate_start(tmp_path: Path, started: bool) -> None:
    with OntologyEvaluationEvidence(tmp_path / "attempt.jsonl") as evidence:
        if started:
            evidence.record("started", {})
        with pytest.raises(OntologyEvaluationEvidenceError):
            evidence.record("started" if started else "completed", {})


@pytest.mark.parametrize("source_commit", ["", "short", "A" * 40, "x" * 40])
def test_rejects_invalid_source_commit_without_creating_file(
    tmp_path: Path, source_commit: str
) -> None:
    path = tmp_path / "attempt.jsonl"
    with pytest.raises(ValueError, match="full lowercase Git SHA"):
        OntologyEvaluationEvidence(path, source_commit=source_commit)
    assert not path.exists()


async def test_slow_recording_does_not_grant_an_expired_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "attempt.jsonl"
    harness, embedder = await _harness(), _BoundEmbedder()
    loop = asyncio.get_running_loop()
    original_time, original_write = loop.time, os.write
    offset = 0.0

    def slow_write(descriptor: int, data: memoryview) -> int:
        nonlocal offset
        if json.loads(bytes(data))["event"] == "embedding_call_intent":
            offset = 2.0
        return original_write(descriptor, data)

    monkeypatch.setattr(loop, "time", lambda: original_time() + offset)
    monkeypatch.setattr(evidence_module.os, "write", slow_write)
    with OntologyEvaluationEvidence(path) as evidence:
        with pytest.raises(OntologyRetrievalExecutionAbortedError) as failure:
            await _execute(harness, embedder, evidence=evidence)
    assert failure.value.embedding_calls == embedder.calls == 0
    records = _records(path)
    assert records[-2]["event"] == "embedding_call_intent"
    assert records[-1]["event"] == "aborted"
    assert records[-1]["payload"]["embedding_calls"] == 0
