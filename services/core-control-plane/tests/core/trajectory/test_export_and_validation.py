"""Exporter, scanner, quarantine, checksum, offline validation, and replay checks."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.trajectory import (
    DatasetGovernance,
    SourceRecordDigest,
    TrajectoryEnvelope,
    TrajectoryStep,
    TrajectoryStepKind,
    TrajectoryTerminalOutcome,
    catalog_tool_statistics,
)
from fdai.core.trajectory.scanning import ScanFindingKind, scan_envelope
from fdai.core.trajectory.serialization import canonical_json_bytes
from fdai.core.trajectory.validation import (
    TrajectoryValidationError,
    replay_check,
    validate_export,
)
from fdai.delivery.trajectory.exporter import (
    ExportQuarantineRecord,
    ExportStatus,
    TrajectoryJsonlExporter,
)

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
DIGEST = "a" * 64
SCOPE_DIGEST = "b" * 64
PURPOSE = "quality-review"


def _envelope(
    *,
    trajectory_id: str = "trajectory-1",
    trace_id: str = "trace-1",
    correlation_id: str = "correlation-1",
    payload: dict[str, object] | None = None,
    purpose: str = PURPOSE,
    scope_digest: str = SCOPE_DIGEST,
) -> TrajectoryEnvelope:
    source = SourceRecordDigest("audit", f"audit-{trajectory_id}", DIGEST)
    return TrajectoryEnvelope(
        trajectory_id=trajectory_id,
        trace_id=trace_id,
        correlation_id=correlation_id,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        environment="test",
        evidence_profile="reviewed",
        principal_scope_digest=scope_digest,
        model_capability_id="t1.judge",
        completion_status=TrajectoryTerminalOutcome.COMPLETED,
        redaction_policy_version="1.0",
        governance=DatasetGovernance(
            purpose=purpose,
            retention_until=NOW + timedelta(days=30),
            deletion_due_at=NOW + timedelta(days=31),
        ),
        source_records=(source,),
        steps=(
            TrajectoryStep(
                sequence=0,
                occurred_at=NOW,
                kind=TrajectoryStepKind.TERMINAL_OUTCOME,
                source=source,
                payload={"outcome": "completed", **(payload or {})},
            ),
        ),
        tool_statistics=catalog_tool_statistics(("a-used",), {"a-used": (1, 1, 0)}),
    )


class RecordingQuarantine:
    def __init__(self) -> None:
        self.records: list[ExportQuarantineRecord] = []

    async def put(self, record: ExportQuarantineRecord) -> None:
        self.records.append(record)


async def _stream(*records: TrajectoryEnvelope) -> AsyncIterator[TrajectoryEnvelope]:
    for record in records:
        yield record


async def _export(
    tmp_path: Path,
    *records: TrajectoryEnvelope,
    quarantine: RecordingQuarantine | None = None,
    is_cancelled: object = None,
) -> tuple[object, Path, Path, RecordingQuarantine]:
    store = quarantine or RecordingQuarantine()
    output = tmp_path / "set.trajectory.jsonl"
    exporter = TrajectoryJsonlExporter(quarantine=store)
    kwargs: dict[str, object] = {}
    if is_cancelled is not None:
        kwargs["is_cancelled"] = is_cancelled
    result = await exporter.export(
        dataset_id="dataset-1",
        records=_stream(*records),
        output_path=output,
        purpose=PURPOSE,
        principal_scope_digest=SCOPE_DIGEST,
        **kwargs,  # type: ignore[arg-type]
    )
    return result, output, output.with_name(output.name + ".manifest.json"), store


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def test_scanner_passes_a_clean_envelope() -> None:
    assert scan_envelope(_envelope()) == ()


@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        ({"note": "Authorization: Bearer abcdefghijklmnop"}, ScanFindingKind.SENSITIVE),
        ({"note": "api_key=super-secret-value"}, ScanFindingKind.SENSITIVE),
        ({"note": "/subscriptions/contoso-sub/resourceGroups/rg"}, ScanFindingKind.IDENTIFIER),
        ({"note": "operator@contoso.test"}, ScanFindingKind.IDENTIFIER),
    ],
)
def test_scanner_flags_secrets_and_identifiers(
    payload: dict[str, object], kind: ScanFindingKind
) -> None:
    findings = scan_envelope(_envelope(payload=payload))

    assert kind in {finding.kind for finding in findings}


def test_scanner_never_echoes_the_matched_value() -> None:
    findings = scan_envelope(_envelope(payload={"note": "api_key=super-secret-value"}))

    assert findings
    assert all("super-secret-value" not in finding.code for finding in findings)


# ---------------------------------------------------------------------------
# Exporter and quarantine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_publishes_data_and_manifest_atomically(tmp_path: Path) -> None:
    result, dataset, manifest, store = await _export(tmp_path, _envelope())

    assert result.status is ExportStatus.COMPLETED  # type: ignore[attr-defined]
    assert dataset.exists() and manifest.exists()
    assert store.records == []
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.asyncio
async def test_a_scanned_record_quarantines_and_publishes_nothing(tmp_path: Path) -> None:
    store = RecordingQuarantine()
    result, dataset, manifest, _ = await _export(
        tmp_path,
        _envelope(payload={"note": "api_key=super-secret-value"}),
        quarantine=store,
    )

    assert result.status is ExportStatus.QUARANTINED  # type: ignore[attr-defined]
    assert not dataset.exists() and not manifest.exists()
    assert store.records[0].trajectory_id == "trajectory-1"
    assert store.records[0].findings


@pytest.mark.asyncio
async def test_cancellation_leaves_no_artifact(tmp_path: Path) -> None:
    result, dataset, manifest, _ = await _export(tmp_path, _envelope(), is_cancelled=lambda: True)

    assert result.status is ExportStatus.CANCELLED  # type: ignore[attr-defined]
    assert not dataset.exists() and not manifest.exists()


@pytest.mark.asyncio
async def test_export_rejects_a_purpose_or_scope_mismatch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="purpose"):
        await _export(tmp_path, _envelope(purpose="other"))
    with pytest.raises(ValueError, match="scope"):
        await _export(tmp_path, _envelope(scope_digest="c" * 64))


@pytest.mark.asyncio
async def test_export_requires_the_governed_file_suffix(tmp_path: Path) -> None:
    exporter = TrajectoryJsonlExporter(quarantine=RecordingQuarantine())
    with pytest.raises(ValueError, match="trajectory export path"):
        await exporter.export(
            dataset_id="dataset-1",
            records=_stream(_envelope()),
            output_path=tmp_path / "set.jsonl",
            purpose=PURPOSE,
            principal_scope_digest=SCOPE_DIGEST,
        )


# ---------------------------------------------------------------------------
# Offline validation and checksums
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_clean_export_validates_offline(tmp_path: Path) -> None:
    _, dataset, manifest, _ = await _export(
        tmp_path,
        _envelope(trajectory_id="a", trace_id="trace-a", correlation_id="corr-a"),
        _envelope(trajectory_id="b", trace_id="trace-b", correlation_id="corr-b"),
    )

    validated = validate_export(dataset, manifest)

    assert len(validated.records) == 2
    assert validated.manifest["purpose"] == PURPOSE


@pytest.mark.asyncio
async def test_a_tampered_record_fails_the_record_checksum(tmp_path: Path) -> None:
    _, dataset, manifest, _ = await _export(tmp_path, _envelope())
    wrapper = json.loads(dataset.read_text(encoding="utf-8"))
    wrapper["record"]["environment"] = "production"
    dataset.write_bytes(canonical_json_bytes(wrapper) + b"\n")

    with pytest.raises(TrajectoryValidationError, match="record checksum"):
        validate_export(dataset, manifest)


@pytest.mark.asyncio
async def test_a_tampered_manifest_fails_its_own_checksum(tmp_path: Path) -> None:
    _, dataset, manifest, _ = await _export(tmp_path, _envelope())
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["purpose"] = "training"
    manifest.write_bytes(canonical_json_bytes(payload) + b"\n")

    with pytest.raises(TrajectoryValidationError, match="manifest checksum"):
        validate_export(dataset, manifest)


@pytest.mark.asyncio
async def test_a_truncated_dataset_fails_the_dataset_checksum(tmp_path: Path) -> None:
    _, dataset, manifest, _ = await _export(
        tmp_path,
        _envelope(trajectory_id="a", trace_id="trace-a", correlation_id="corr-a"),
        _envelope(trajectory_id="b", trace_id="trace-b", correlation_id="corr-b"),
    )
    first = dataset.read_bytes().splitlines(keepends=True)[0]
    dataset.write_bytes(first)

    with pytest.raises(TrajectoryValidationError, match="record count"):
        validate_export(dataset, manifest)


def test_a_missing_export_is_reported_as_incomplete(tmp_path: Path) -> None:
    with pytest.raises(TrajectoryValidationError, match="incomplete or unreadable"):
        validate_export(tmp_path / "absent.trajectory.jsonl", tmp_path / "absent.manifest.json")


# ---------------------------------------------------------------------------
# Judge-only replay
# ---------------------------------------------------------------------------


def test_replay_accepts_canonically_ordered_unique_records() -> None:
    replay_check(
        (
            _envelope(trajectory_id="a", trace_id="trace-a", correlation_id="corr-a"),
            _envelope(trajectory_id="b", trace_id="trace-b", correlation_id="corr-b"),
        )
    )


def test_replay_rejects_unordered_or_duplicated_records() -> None:
    first = _envelope(trajectory_id="a", trace_id="trace-b", correlation_id="corr-b")
    second = _envelope(trajectory_id="b", trace_id="trace-a", correlation_id="corr-a")

    with pytest.raises(TrajectoryValidationError, match="order or identity"):
        replay_check((first, second))
    with pytest.raises(TrajectoryValidationError, match="order or identity"):
        replay_check((first, first))


def test_replay_rejects_a_broken_step_source_mapping() -> None:
    envelope = _envelope()
    detached = SourceRecordDigest("audit", "audit-other", DIGEST)
    broken = replace(envelope, steps=(replace(envelope.steps[0], source=detached),))

    with pytest.raises(TrajectoryValidationError, match="source mapping"):
        replay_check((broken,))
