"""Private vector capture and exact offline execution, without model or network calls."""

import hashlib
import json
import os
from pathlib import Path

import pytest
from fdai.delivery.catalog_search import ontology_evaluation_evidence as evidence_module
from fdai.delivery.catalog_search import ontology_evaluation_replay as replay_module
from fdai.delivery.catalog_search.ontology_evaluation_evidence import (
    OntologyEvaluationEvidence,
    OntologyEvaluationEvidenceError,
)
from fdai.delivery.catalog_search.ontology_evaluation_replay import (
    OntologyEvaluationReplayEmbedder,
)
from tests.delivery.catalog_search.test_ontology_evaluation_campaign import _calibration
from tests.delivery.catalog_search.test_ontology_evaluation_execution import (
    _BoundEmbedder,
    _execute,
)
from tests.delivery.catalog_search.test_ontology_evaluation_runner import _harness

_IDENTITY = ("test-space", "test-model-v1", 4)
_SOURCE = "a" * 40


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _replay(path: Path) -> OntologyEvaluationReplayEmbedder:
    return OntologyEvaluationReplayEmbedder.from_evidence(
        path,
        expected_file_digest=_digest(path),
        expected_source_commit=_SOURCE,
        expected_identity=_IDENTITY,
    )


async def _capture(path: Path, *, retain_vectors: bool = True) -> None:
    with OntologyEvaluationEvidence(
        path, source_commit=_SOURCE, retain_vectors=retain_vectors
    ) as evidence:
        await _execute(await _harness(), _BoundEmbedder(), evidence=evidence)


async def test_replays_the_actual_reader_with_exact_results_and_explicit_offline_origin(
    tmp_path: Path,
) -> None:
    path = tmp_path / "captured.jsonl"
    harness, provider = await _harness(), _BoundEmbedder()
    with OntologyEvaluationEvidence(path, source_commit=_SOURCE, retain_vectors=True) as evidence:
        captured = await _execute(harness, provider, evidence=evidence)
    records = [json.loads(line) for line in path.read_bytes().splitlines()]
    vectors = [item for item in records if item["event"] == "embedding_result"]
    assert len(vectors) == provider.calls == 32
    assert [item["payload"]["call_index"] for item in vectors] == list(range(1, 33))
    assert all("text" not in item["payload"] for item in vectors)
    assert path.stat().st_mode & 0o777 == 0o600
    replay = _replay(path)
    result = await _execute(harness, replay)
    assert provider.calls == 32
    assert result.campaign == captured.campaign
    assert result.embedding_source == "offline_replay"
    assert result.replay_evidence_digest == _digest(path)
    assert result.embedding_calls == 32
    assert result.production_qualification is result.execution_authority is False
    assert captured.embedding_source == "caller_supplied"
    assert captured.replay_evidence_digest is None


async def test_default_does_not_retain_vectors_or_offer_a_silent_replay(tmp_path: Path) -> None:
    path = tmp_path / "no-vectors.jsonl"
    await _capture(path, retain_vectors=False)
    assert b'"embedding_result"' not in path.read_bytes()
    with pytest.raises(ValueError, match="incomplete, invalid or inconsistent"):
        _replay(path)


async def test_unknown_exact_text_fails_without_live_fallback_or_text_disclosure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "capture.jsonl"
    await _capture(path)
    replay = _replay(path)
    with pytest.raises(ValueError, match="no vector for the exact input") as failure:
        await replay.embed("private-unknown-query")
    assert "private-unknown-query" not in str(failure.value)


@pytest.mark.parametrize("variant", ["case", "whitespace"])
async def test_replay_never_normalizes_embedding_input_bytes(tmp_path: Path, variant: str) -> None:
    path = tmp_path / "exact-text.jsonl"
    await _capture(path)
    replay = _replay(path)
    query = _calibration()[0].query
    assert len(await replay.embed(query)) == 4
    with pytest.raises(ValueError, match="no vector for the exact input"):
        await replay.embed(query.upper() if variant == "case" else " " + query)


@pytest.mark.parametrize("limit", ["_MAX_FILE_BYTES", "_MAX_RECORD_BYTES"])
async def test_replay_enforces_file_and_record_byte_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    path = tmp_path / "bounded.jsonl"
    await _capture(path)
    monkeypatch.setattr(replay_module, limit, 1)
    with pytest.raises(ValueError):
        _replay(path)


@pytest.mark.parametrize(
    "damage",
    [
        "sequence",
        "source",
        "space",
        "model",
        "dimension",
        "no-intent",
        "no-result",
        "result-first",
        "conflicting-vector",
        "nonfinite",
        "zero",
        "boolean",
        "string",
        "digest",
        "no-terminal",
        "extra-terminal",
        "count",
        "replay-origin",
        "partial-tail",
    ],
)
async def test_rejects_inconsistent_evidence_even_with_its_new_file_digest(
    tmp_path: Path, damage: str
) -> None:
    path = tmp_path / "damaged.jsonl"
    await _capture(path)
    records = [json.loads(line) for line in path.read_bytes().splitlines()]
    result = records[2]["payload"]
    if damage == "sequence":
        records[2]["sequence"] = 99
    elif damage == "source":
        records[2]["source_commit"] = "b" * 40
    elif damage in ("space", "model"):
        result[f"embedding_{'space_id' if damage == 'space' else 'model_version'}"] = "changed"
    elif damage == "dimension":
        result["embedding_dimension"] = 3
    elif damage == "no-intent":
        records.pop(1)
    elif damage == "no-result":
        records.pop(2)
    elif damage == "result-first":
        records[1], records[2] = records[2], records[1]
    elif damage == "conflicting-vector":
        records[4]["payload"]["text_digest"] = result["text_digest"]
        records[4]["payload"]["vector"] = [-value for value in result["vector"]]
    elif damage in ("nonfinite", "zero", "boolean", "string"):
        value = {"nonfinite": float("nan"), "zero": 0.0, "boolean": True, "string": "1.0"}[damage]
        result["vector"] = [value] * 4
    elif damage == "digest":
        result["text_digest"] = "invalid"
    elif damage == "no-terminal":
        records.pop()
    elif damage == "extra-terminal":
        records.insert(3, records[-1])
    elif damage == "count":
        records[-1]["payload"]["report"]["embedding_calls"] -= 1
    elif damage == "replay-origin":
        records[-1]["payload"]["report"]["embedding_source"] = "offline_replay"
    if damage != "sequence":
        for index, record in enumerate(records):
            record["sequence"] = index
    encoded = "\n".join(json.dumps(item) for item in records) + "\n"
    path.write_text(encoded.rstrip() if damage == "partial-tail" else encoded)
    with pytest.raises(ValueError, match="incomplete, invalid or inconsistent"):
        _replay(path)


@pytest.mark.parametrize(
    "damage", ["file-digest", "source", "model", "symlink", "public", "missing"]
)
async def test_rejects_changed_expected_bindings_or_unsafe_files(
    tmp_path: Path, damage: str
) -> None:
    path = tmp_path / "capture.jsonl"
    await _capture(path)
    digest = _digest(path)
    if damage == "symlink":
        link = tmp_path / "link.jsonl"
        link.symlink_to(path)
        path = link
    elif damage == "public":
        path.chmod(0o644)
    elif damage == "missing":
        path = tmp_path / "private-missing-file"
    with pytest.raises(ValueError) as failure:
        OntologyEvaluationReplayEmbedder.from_evidence(
            path,
            expected_file_digest="sha256:" + "0" * 64 if damage == "file-digest" else digest,
            expected_source_commit="b" * 40 if damage == "source" else _SOURCE,
            expected_identity=("changed", "test-model-v1", 4) if damage == "model" else _IDENTITY,
        )
    assert "private-missing-file" not in str(failure.value)


async def test_vector_persistence_failure_stops_before_next_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "failed.jsonl"
    provider = _BoundEmbedder()
    original_write = os.write

    def fail_result(descriptor: int, data: memoryview) -> int:
        if json.loads(bytes(data))["event"] == "embedding_result":
            raise OSError("private-storage-detail")
        return original_write(descriptor, data)

    monkeypatch.setattr(evidence_module.os, "write", fail_result)
    with OntologyEvaluationEvidence(path, source_commit=_SOURCE, retain_vectors=True) as evidence:
        with pytest.raises(OntologyEvaluationEvidenceError) as failure:
            await _execute(await _harness(), provider, evidence=evidence)
    assert provider.calls == 1
    assert "private-storage-detail" not in str(failure.value)
    assert b'"completed"' not in path.read_bytes()


def test_opt_in_capacity_covers_every_bounded_call_and_remains_finite(tmp_path: Path) -> None:
    with OntologyEvaluationEvidence(
        tmp_path / "capacity.jsonl", source_commit=_SOURCE, retain_vectors=True
    ) as evidence:
        evidence.record("started", {})
        for index in range(128):
            evidence.record("embedding_call_intent", {"call_index": index + 1})
            evidence.record("embedding_result", {"call_index": index + 1})
        evidence.record("stage", {})
        evidence.record("stage", {})
        evidence.record("completed", {})
    with OntologyEvaluationEvidence(
        tmp_path / "overflow.jsonl", source_commit=_SOURCE, retain_vectors=True
    ) as evidence:
        evidence.record("started", {})
        for _index in range(261):
            evidence.record("stage", {})
        with pytest.raises(OntologyEvaluationEvidenceError):
            evidence.record("stage", {})


def test_vector_capture_requires_a_source_pin_before_opening_a_file(tmp_path: Path) -> None:
    path = tmp_path / "missing-source.jsonl"
    with pytest.raises(ValueError, match="requires a source commit"):
        OntologyEvaluationEvidence(path, retain_vectors=True)
    assert not path.exists()
