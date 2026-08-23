"""Gate and execute safe-to-retry operational-history source purges."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from fdai.core.ontology_platform.archive_manifest import (
    ArchiveManifest,
    ArchiveVerificationReceipt,
)
from fdai.core.ontology_platform.archive_retention import (
    ArchiveRestoreReceipt,
    RetentionEvaluationReceipt,
)


class ArchivePurgeStatus(StrEnum):
    """Describe one append-only purge phase or terminal outcome."""

    BLOCKED = "blocked"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class ArchivePurgeReceipt:
    """Record purge gates, source preservation, and storage pressure."""

    idempotency_key: str
    attempt: int
    manifest_digest: str
    status: ArchivePurgeStatus
    reason_codes: tuple[str, ...]
    source_data_preserved: bool
    storage_pressure: bool
    recorded_at: datetime
    digest: str


class ArchivePurgeReceiptStore(Protocol):
    """Persist append-only purge phases and resolve successful retries."""

    async def latest(self, idempotency_key: str) -> ArchivePurgeReceipt | None: ...

    async def append(self, receipt: ArchivePurgeReceipt) -> None: ...


class ArchiveSourcePurger(Protocol):
    """Delete exact source partitions idempotently after all gates pass."""

    async def purge(self, partition_ids: tuple[str, ...]) -> None: ...


class OperationalArchivePurgeCoordinator:
    """Write a durable intent before calling the source purger."""

    def __init__(
        self,
        *,
        receipts: ArchivePurgeReceiptStore,
        source: ArchiveSourcePurger,
    ) -> None:
        self._receipts = receipts
        self._source = source

    async def purge(
        self,
        manifest: ArchiveManifest,
        verification: ArchiveVerificationReceipt,
        restore: ArchiveRestoreReceipt,
        retention: RetentionEvaluationReceipt,
        *,
        idempotency_key: str,
        recorded_at: datetime,
    ) -> ArchivePurgeReceipt:
        """Purge only after verification, restore, and hold gates pass."""

        if not idempotency_key or len(idempotency_key) > 256:
            raise ValueError("archive purge idempotency_key MUST be bounded and non-empty")
        if recorded_at.tzinfo is None:
            raise ValueError("archive purge recorded_at MUST be timezone-aware")
        prior = await self._receipts.latest(idempotency_key)
        if prior is not None and prior.status is ArchivePurgeStatus.SUCCEEDED:
            return _receipt(
                idempotency_key=idempotency_key,
                attempt=prior.attempt,
                manifest_digest=manifest.digest,
                status=ArchivePurgeStatus.DUPLICATE,
                reasons=("already_purged",),
                source_data_preserved=False,
                storage_pressure=False,
                recorded_at=recorded_at,
            )
        attempt = 1 if prior is None else prior.attempt + 1
        reasons = _gate_reasons(manifest, verification, restore, retention)
        if reasons:
            blocked = _receipt(
                idempotency_key=idempotency_key,
                attempt=attempt,
                manifest_digest=manifest.digest,
                status=ArchivePurgeStatus.BLOCKED,
                reasons=reasons,
                source_data_preserved=True,
                storage_pressure=True,
                recorded_at=recorded_at,
            )
            await self._receipts.append(blocked)
            return blocked
        pending = _receipt(
            idempotency_key=idempotency_key,
            attempt=attempt,
            manifest_digest=manifest.digest,
            status=ArchivePurgeStatus.PENDING,
            reasons=(),
            source_data_preserved=True,
            storage_pressure=False,
            recorded_at=recorded_at,
        )
        await self._receipts.append(pending)
        try:
            await self._source.purge(
                tuple(item.partition_id for item in manifest.source_partitions)
            )
        except Exception:
            failed = _receipt(
                idempotency_key=idempotency_key,
                attempt=attempt,
                manifest_digest=manifest.digest,
                status=ArchivePurgeStatus.FAILED,
                reasons=("source_purge_failed",),
                source_data_preserved=True,
                storage_pressure=True,
                recorded_at=recorded_at,
            )
            await self._receipts.append(failed)
            return failed
        succeeded = _receipt(
            idempotency_key=idempotency_key,
            attempt=attempt,
            manifest_digest=manifest.digest,
            status=ArchivePurgeStatus.SUCCEEDED,
            reasons=(),
            source_data_preserved=False,
            storage_pressure=False,
            recorded_at=recorded_at,
        )
        await self._receipts.append(succeeded)
        return succeeded


def _gate_reasons(
    manifest: ArchiveManifest,
    verification: ArchiveVerificationReceipt,
    restore: ArchiveRestoreReceipt,
    retention: RetentionEvaluationReceipt,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if verification.manifest_digest != manifest.digest or not verification.verified:
        reasons.append("manifest_unverified")
    if restore.manifest_digest != manifest.digest or not restore.passed:
        reasons.append("restore_sample_failed")
    if retention.manifest_digest != manifest.digest or not retention.permitted:
        reasons.append("retention_hold_active")
    return tuple(reasons)


def _receipt(
    *,
    idempotency_key: str,
    attempt: int,
    manifest_digest: str,
    status: ArchivePurgeStatus,
    reasons: tuple[str, ...],
    source_data_preserved: bool,
    storage_pressure: bool,
    recorded_at: datetime,
) -> ArchivePurgeReceipt:
    body = {
        "idempotency_key": idempotency_key,
        "attempt": attempt,
        "manifest_digest": manifest_digest,
        "status": status.value,
        "reason_codes": reasons,
        "source_data_preserved": source_data_preserved,
        "storage_pressure": storage_pressure,
        "recorded_at": recorded_at.astimezone(UTC).isoformat(),
    }
    return ArchivePurgeReceipt(
        idempotency_key=idempotency_key,
        attempt=attempt,
        manifest_digest=manifest_digest,
        status=status,
        reason_codes=reasons,
        source_data_preserved=source_data_preserved,
        storage_pressure=storage_pressure,
        recorded_at=recorded_at,
        digest="sha256:"
        + hashlib.sha256(
            json.dumps(
                body,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest(),
    )


__all__ = [
    "ArchivePurgeReceipt",
    "ArchivePurgeReceiptStore",
    "ArchivePurgeStatus",
    "ArchiveSourcePurger",
    "OperationalArchivePurgeCoordinator",
]
