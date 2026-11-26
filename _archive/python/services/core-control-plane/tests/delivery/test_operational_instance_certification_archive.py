"""Local OI-12 rollup, archive, and restore exercise tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.ontology_platform.archive_manifest import (
    ArchiveManifest,
    ArchiveVerificationReceipt,
)
from fdai.core.ontology_platform.archive_retention import ArchiveRestoreReceipt
from fdai.delivery.operational_instance_certification import (
    build_operational_certification_snapshot,
)
from fdai.delivery.operational_instance_certification_archive import (
    run_local_archive_exercise,
)
from fdai.delivery.operational_instance_certification_cli import archive_exercise_record

_START = datetime(2026, 8, 25, tzinfo=UTC)
_RELEASE = "sha256:" + "a" * 64


class _Store:
    def __init__(self) -> None:
        self.manifests: list[ArchiveManifest] = []
        self.verifications: list[ArchiveVerificationReceipt] = []
        self.restores: list[ArchiveRestoreReceipt] = []

    async def put_manifest(self, manifest: ArchiveManifest) -> bool:
        self.manifests.append(manifest)
        return True

    async def append_verification(self, receipt: ArchiveVerificationReceipt) -> bool:
        self.verifications.append(receipt)
        return True

    async def append_restore(self, receipt: ArchiveRestoreReceipt) -> bool:
        self.restores.append(receipt)
        return True


class _VerificationFailureStore(_Store):
    async def append_verification(self, receipt: ArchiveVerificationReceipt) -> bool:
        raise RuntimeError("verification persistence unavailable")


def _snapshot(*, measured_at: datetime, database_bytes: int, release: str = _RELEASE):
    return build_operational_certification_snapshot(
        measured_at=measured_at,
        ontology_release_digest=release,
        database_bytes=database_bytes,
        freshness_seconds=None,
        api_pressure_ratio=None,
        lag_seconds=None,
        rollup_total_count=0,
        rollup_complete_count=0,
        restore_total_count=0,
        restore_passed_count=0,
        provider_failure_recovery_seconds=None,
    )


async def test_local_archive_exercise_writes_and_restores_real_private_artifact(
    tmp_path: Path,
) -> None:
    store = _Store()
    artifact = tmp_path / "oi12" / "rollup.json"

    receipt = await run_local_archive_exercise(
        _snapshot(measured_at=_START, database_bytes=1000),
        _snapshot(measured_at=_START + timedelta(minutes=5), database_bytes=1200),
        artifact_path=artifact,
        store=store,
    )

    assert artifact.stat().st_mode & 0o777 == 0o600
    assert receipt.passed is True
    assert receipt.observation_authority is False
    assert receipt.mutation_authority is False
    assert receipt.execution_authority is False
    assert len(store.manifests) == len(store.verifications) == len(store.restores) == 1
    assert store.manifests[0].coverage_complete is True
    assert store.verifications[0].verified is True
    assert store.restores[0].passed is True
    assert archive_exercise_record(receipt) == {
        "schema_version": "1.0.0",
        "rollup_digest": receipt.rollup_digest,
        "manifest_digest": receipt.manifest_digest,
        "verification_digest": receipt.verification_digest,
        "restore_digest": receipt.restore_digest,
        "artifact_digest": receipt.artifact_digest,
        "passed": True,
        "observation_authority": False,
        "mutation_authority": False,
        "execution_authority": False,
        "digest": receipt.digest,
    }


async def test_local_archive_exercise_rejects_release_drift(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="same ontology release"):
        await run_local_archive_exercise(
            _snapshot(measured_at=_START, database_bytes=1000),
            _snapshot(
                measured_at=_START + timedelta(minutes=1),
                database_bytes=1001,
                release="sha256:" + "b" * 64,
            ),
            artifact_path=tmp_path / "rollup.json",
            store=_Store(),
        )


async def test_local_archive_exercise_emits_no_receipt_after_partial_store_failure(
    tmp_path: Path,
) -> None:
    store = _VerificationFailureStore()

    with pytest.raises(RuntimeError, match="verification persistence unavailable"):
        await run_local_archive_exercise(
            _snapshot(measured_at=_START, database_bytes=1000),
            _snapshot(measured_at=_START + timedelta(minutes=1), database_bytes=1001),
            artifact_path=tmp_path / "rollup.json",
            store=store,
        )

    assert len(store.manifests) == 1
    assert store.verifications == []
    assert store.restores == []
