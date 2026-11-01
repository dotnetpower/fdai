"""Focused tests for `fdaictl trajectory validate` offline validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fdai_deployment_cli.cli import main
from fdai_deployment_cli.trajectory_cli import canonical_json_bytes

SCOPE_A = "a" * 64
SCOPE_B = "b" * 64
SOURCE_HASH = "c" * 64


def _sample_record(
    *,
    trace_id: str = "trace-001",
    correlation_id: str = "corr-001",
    purpose: str = "quality-evaluation",
    scope_digest: str = SCOPE_A,
    source_id: str = "audit-1",
    step_source_id: str = "audit-1",
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "trajectory_id": f"traj-{trace_id}",
        "trace_id": trace_id,
        "correlation_id": correlation_id,
        "started_at": "2026-11-01T00:00:00+00:00",
        "completed_at": "2026-11-01T00:00:05+00:00",
        "environment": "dev",
        "evidence_profile": "synthetic",
        "principal_scope_digest": scope_digest,
        "model_capability_id": "t2.reasoner",
        "completion_status": "completed",
        "redaction_policy_version": "1.0",
        "governance": {
            "purpose": purpose,
            "retention_until": "2026-12-01T00:00:00+00:00",
            "deletion_due_at": "2026-12-02T00:00:00+00:00",
            "legal_hold": False,
            "legal_hold_ref": None,
        },
        "source_records": [
            {
                "record_type": "audit_entry",
                "record_id": source_id,
                "sha256": SOURCE_HASH,
            }
        ],
        "steps": [
            {
                "sequence": 0,
                "occurred_at": "2026-11-01T00:00:01+00:00",
                "kind": "routing_decision",
                "source": {
                    "record_type": "audit_entry",
                    "record_id": step_source_id,
                    "sha256": SOURCE_HASH,
                },
                "payload": {"tier": "T0"},
            }
        ],
        "tool_statistics": [
            {
                "tool_name": "inventory.read",
                "request_count": 1,
                "error_count": 0,
            }
        ],
    }


def _write_export(
    tmp_path: Path,
    *,
    records: list[dict[str, object]],
    manifest_purpose: str = "quality-evaluation",
    manifest_scope: str = SCOPE_A,
    tamper_manifest: bool = False,
    tamper_record: bool = False,
) -> tuple[Path, Path]:
    dataset_path = tmp_path / "sample.trajectory.jsonl"
    manifest_path = tmp_path / "sample.trajectory.jsonl.manifest.json"
    dataset_hasher = hashlib.sha256()
    raw_lines: list[bytes] = []
    for rec in records:
        checksum = hashlib.sha256(canonical_json_bytes(rec)).hexdigest()
        if tamper_record:
            checksum = "0" * 64
        line = canonical_json_bytes({"checksum": checksum, "record": rec}) + b"\n"
        raw_lines.append(line)
        dataset_hasher.update(line)
    dataset_path.write_bytes(b"".join(raw_lines))

    manifest: dict[str, object] = {
        "dataset_id": "ds-001",
        "schema_version": "1.0",
        "purpose": manifest_purpose,
        "principal_scope_digest": manifest_scope,
        "record_count": len(records),
        "outcome_counts": {"completed": len(records)},
        "dataset_checksum": dataset_hasher.hexdigest(),
    }
    manifest_checksum = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    manifest["manifest_checksum"] = "f" * 64 if tamper_manifest else manifest_checksum
    manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")
    return dataset_path, manifest_path


def test_fdaictl_trajectory_validate_passes_on_valid_export(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset_path, manifest_path = _write_export(tmp_path, records=[_sample_record()])
    rc = main(
        [
            "trajectory",
            "validate",
            "--dataset",
            str(dataset_path),
            "--manifest",
            str(manifest_path),
            "--purpose",
            "quality-evaluation",
            "--access-scope",
            SCOPE_A,
            "--output",
            "json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dataset_id"] == "ds-001"
    assert payload["record_count"] == 1
    assert payload["replay_verified"] is True
    assert payload["training_authority"] == "none"
    assert payload["promotion_authority"] == "none"


def test_fdaictl_trajectory_validate_rejects_purpose_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset_path, manifest_path = _write_export(tmp_path, records=[_sample_record()])
    rc = main(
        [
            "trajectory",
            "validate",
            "--dataset",
            str(dataset_path),
            "--manifest",
            str(manifest_path),
            "--purpose",
            "wrong-purpose",
            "--access-scope",
            SCOPE_A,
        ]
    )
    assert rc == 3
    assert "purpose does not match" in capsys.readouterr().err


def test_fdaictl_trajectory_validate_rejects_access_scope_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset_path, manifest_path = _write_export(tmp_path, records=[_sample_record()])
    rc = main(
        [
            "trajectory",
            "validate",
            "--dataset",
            str(dataset_path),
            "--manifest",
            str(manifest_path),
            "--purpose",
            "quality-evaluation",
            "--access-scope",
            SCOPE_B,
        ]
    )
    assert rc == 3
    assert "access_scope does not match" in capsys.readouterr().err


def test_fdaictl_trajectory_validate_rejects_record_scope_drift_and_tampered_checksums(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_rec = _sample_record(scope_digest=SCOPE_B)
    dataset_path, manifest_path = _write_export(
        tmp_path,
        records=[bad_rec],
        manifest_scope=SCOPE_A,
    )
    rc = main(
        [
            "trajectory",
            "validate",
            "--dataset",
            str(dataset_path),
            "--manifest",
            str(manifest_path),
            "--purpose",
            "quality-evaluation",
            "--access-scope",
            SCOPE_A,
        ]
    )
    assert rc == 3
    assert "record access_scope does not match" in capsys.readouterr().err

    tampered_ds, tampered_mf = (
        _write_export(
            tmp_path / "sub",
            records=[],
            tamper_manifest=True,
        )
        if False
        else (None, None)
    )
    sub = tmp_path / "tampered"
    sub.mkdir()
    tampered_ds, tampered_mf = _write_export(
        sub,
        records=[_sample_record()],
        tamper_record=True,
    )
    rc2 = main(
        [
            "trajectory",
            "validate",
            "--dataset",
            str(tampered_ds),
            "--manifest",
            str(tampered_mf),
            "--purpose",
            "quality-evaluation",
            "--access-scope",
            SCOPE_A,
        ]
    )
    assert rc2 == 3
    assert "record checksum mismatch" in capsys.readouterr().err


def test_fdaictl_trajectory_validate_rejects_broken_replay_order_and_source_mapping(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unordered = [
        _sample_record(trace_id="trace-002", correlation_id="corr-002"),
        _sample_record(trace_id="trace-001", correlation_id="corr-001"),
    ]
    dataset_path, manifest_path = _write_export(tmp_path, records=unordered)
    rc = main(
        [
            "trajectory",
            "validate",
            "--dataset",
            str(dataset_path),
            "--manifest",
            str(manifest_path),
            "--purpose",
            "quality-evaluation",
            "--access-scope",
            SCOPE_A,
        ]
    )
    assert rc == 3
    assert "order or identity is invalid" in capsys.readouterr().err

    sub = tmp_path / "broken_source"
    sub.mkdir()
    bad_source = [_sample_record(source_id="audit-1", step_source_id="missing-source")]
    ds2, mf2 = _write_export(sub, records=bad_source)
    rc2 = main(
        [
            "trajectory",
            "validate",
            "--dataset",
            str(ds2),
            "--manifest",
            str(mf2),
            "--purpose",
            "quality-evaluation",
            "--access-scope",
            SCOPE_A,
        ]
    )
    assert rc2 == 3
    assert "step source mapping is broken" in capsys.readouterr().err


def test_fdaictl_trajectory_validate_rejects_inverted_timestamps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inverted = _sample_record()
    inverted["completed_at"] = "2026-10-31T23:59:59+00:00"
    ds, mf = _write_export(tmp_path, records=[inverted])
    rc = main(
        [
            "trajectory",
            "validate",
            "--dataset",
            str(ds),
            "--manifest",
            str(mf),
            "--purpose",
            "quality-evaluation",
            "--access-scope",
            SCOPE_A,
        ]
    )
    assert rc == 3
    assert "completed_at must be >= started_at" in capsys.readouterr().err
