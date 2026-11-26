from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdai_deployment_cli.standalone_migration_evidence import verify_service_evidence


def _write(directory: Path, name: str, value: dict[str, object]) -> None:
    path = directory / name
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o644)


def _evidence(tmp_path: Path) -> Path:
    directory = tmp_path / "migration-evidence"
    directory.mkdir(mode=0o700)
    tmp_path.chmod(0o700)
    return directory


def test_fresh_adoption_evidence_is_verified_and_made_private(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    _write(evidence, "svc.json", {"service_id": "svc", "observed_schema_fingerprint": "f"})
    _write(
        evidence,
        "svc-schema.json",
        {"schema_version": 1, "service_id": "svc", "observed_schema_fingerprint": "f"},
    )

    assert verify_service_evidence(evidence, "svc") is True
    assert (evidence / "svc.json").stat().st_mode & 0o777 == 0o600


def test_already_adopted_lineage_writes_no_evidence(tmp_path: Path) -> None:
    assert verify_service_evidence(_evidence(tmp_path), "svc") is False


def test_partial_or_inconsistent_evidence_fails_closed(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    _write(evidence, "svc.json", {"service_id": "svc", "observed_schema_fingerprint": "f"})
    with pytest.raises((ValueError, OSError)):
        verify_service_evidence(evidence, "svc")

    _write(
        evidence,
        "svc-schema.json",
        {"schema_version": 1, "service_id": "svc", "observed_schema_fingerprint": "other"},
    )
    with pytest.raises(ValueError, match="incomplete"):
        verify_service_evidence(evidence, "svc")
