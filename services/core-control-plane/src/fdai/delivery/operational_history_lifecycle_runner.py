"""Compose one bounded operational-history lifecycle Job pass."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

import httpx
import psycopg

from fdai.core.ontology_platform.archive_manifest import (
    ArchiveManifest,
    ArchiveSourcePartition,
    ArchiveVerificationReceipt,
    build_archive_manifest,
    verify_archive_manifest,
)
from fdai.core.ontology_platform.archive_retention import (
    ArchiveRestoreReceipt,
    RetentionHold,
    evaluate_restore_sample,
    evaluate_retention_holds,
)
from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationCheckpoint,
    ObservationPartition,
    ObservationPartitionPin,
    ObservationPartitionState,
)
from fdai.core.ontology_platform.operational_history_pressure import (
    StoragePressureAssessment,
    StoragePressurePolicy,
)
from fdai.delivery.azure.operational_history_archive import (
    AzureBlobOperationalHistoryArtifactStore,
    AzureBlobOperationalHistoryConfig,
)
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.operational_archive_purge import (
    ArchivePurgeStatus,
    OperationalArchivePurgeCoordinator,
)
from fdai.delivery.operational_history_archive import (
    OperationalArchivePrincipal,
    OperationalHistoryArchiveReader,
    OperationalHistoryArchiveWriter,
)
from fdai.delivery.operational_history_lifecycle import (
    OperationalHistoryLifecycleAction,
    OperationalHistoryLifecycleEvidence,
    plan_operational_history_lifecycle,
)
from fdai.delivery.persistence.postgres_operational_archive import (
    PostgresOperationalArchiveStore,
    PostgresOperationalArchiveStoreConfig,
)
from fdai.delivery.persistence.postgres_operational_history import (
    PostgresOperationalHistoryConfig,
    PostgresOperationalHistoryStore,
)
from fdai.delivery.persistence.postgres_operational_history_lifecycle_runner import (
    PostgresOperationalHistoryLifecycleRepository,
)

_LOGGER = logging.getLogger("fdai.operational_history_lifecycle")
_SCHEMA_VERSION = "inventory-observation-1.0.0"
_PURPOSE = "operational-history-lifecycle"


class OperationalHistoryLifecycleMode(StrEnum):
    """Separate observation, ordinary lifecycle mutation, and purge certification."""

    SHADOW = "shadow"
    ENFORCE = "enforce"
    CERTIFY = "certify"


@dataclass(frozen=True, slots=True)
class OperationalHistoryLifecycleRunnerConfig:
    """Validated environment binding for one scheduled lifecycle pass."""

    dsn: str
    container_url: str
    mode: OperationalHistoryLifecycleMode = OperationalHistoryLifecycleMode.SHADOW
    authority_receipt_digest: str | None = None
    max_partitions: int = 32
    warning_bytes: int = 10 * 1024**3
    critical_bytes: int = 20 * 1024**3
    hard_bytes: int = 30 * 1024**3
    max_purge_backlog: int = 256
    max_projection_lag: int = 1000

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("FDAI_DATABASE_URL is required")
        if not self.container_url:
            raise ValueError("FDAI_OPERATIONAL_HISTORY_CONTAINER_URL is required")
        if not 1 <= self.max_partitions <= 256:
            raise ValueError("operational history max_partitions MUST be in [1, 256]")
        if not 0 < self.warning_bytes < self.critical_bytes < self.hard_bytes:
            raise ValueError("operational history storage byte thresholds MUST be monotonic")
        if self.max_purge_backlog < 1 or self.max_projection_lag < 1:
            raise ValueError("operational history pressure limits MUST be positive")
        if self.mode is not OperationalHistoryLifecycleMode.SHADOW:
            _canonical_digest(self.authority_receipt_digest, "authority receipt")

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str],
        *,
        mode: OperationalHistoryLifecycleMode | None = None,
        authority_receipt_digest: str | None = None,
    ) -> OperationalHistoryLifecycleRunnerConfig:
        """Load bounded deployment configuration without inventing authority."""

        configured_mode = mode or OperationalHistoryLifecycleMode(
            environ.get("FDAI_OPERATIONAL_HISTORY_MODE", "shadow").strip()
        )
        return cls(
            dsn=environ.get("FDAI_DATABASE_URL", "")
            .strip()
            .replace("postgresql+psycopg://", "postgresql://", 1),
            container_url=environ.get("FDAI_OPERATIONAL_HISTORY_CONTAINER_URL", "").strip(),
            mode=configured_mode,
            authority_receipt_digest=authority_receipt_digest
            or _optional(environ.get("FDAI_OPERATIONAL_HISTORY_AUTHORITY_RECEIPT")),
            max_partitions=_bounded_int(environ, "FDAI_OPERATIONAL_HISTORY_MAX_PARTITIONS", 32),
            warning_bytes=_bounded_int(
                environ, "FDAI_OPERATIONAL_HISTORY_WARNING_BYTES", 10 * 1024**3
            ),
            critical_bytes=_bounded_int(
                environ, "FDAI_OPERATIONAL_HISTORY_CRITICAL_BYTES", 20 * 1024**3
            ),
            hard_bytes=_bounded_int(environ, "FDAI_OPERATIONAL_HISTORY_HARD_BYTES", 30 * 1024**3),
            max_purge_backlog=_bounded_int(
                environ, "FDAI_OPERATIONAL_HISTORY_MAX_PURGE_BACKLOG", 256
            ),
            max_projection_lag=_bounded_int(
                environ, "FDAI_OPERATIONAL_HISTORY_MAX_PROJECTION_LAG", 1000
            ),
        )


@dataclass(frozen=True, slots=True)
class OperationalHistoryLifecycleRunResult:
    """Stable no-authority summary for one bounded pass."""

    mode: OperationalHistoryLifecycleMode
    planned: tuple[str, ...]
    applied: tuple[str, ...]
    blocked: tuple[str, ...]
    execution_authority: bool = False

    def as_record(self) -> dict[str, object]:
        """Return a structured Job result without managed-resource authority."""

        return {
            "schema_version": "1.0.0",
            "mode": self.mode.value,
            "planned": list(self.planned),
            "applied": list(self.applied),
            "blocked": list(self.blocked),
            "execution_authority": self.execution_authority,
        }


class OperationalHistoryLifecycleRepository(Protocol):
    """Read lifecycle evidence and commit exact monotonic state transitions."""

    async def assess_pressure(self, policy: StoragePressurePolicy) -> StoragePressureAssessment: ...

    async def list_partitions(
        self, *, limit: int, now: datetime
    ) -> tuple[ObservationPartition, ...]: ...

    async def latest_checkpoint(self, partition_id: str) -> ObservationCheckpoint | None: ...

    async def latest_manifest(self, partition_id: str) -> ArchiveManifest | None: ...

    async def latest_verification(
        self, manifest_digest: str
    ) -> ArchiveVerificationReceipt | None: ...

    async def latest_restore(self, manifest_digest: str) -> ArchiveRestoreReceipt | None: ...

    async def active_pins(
        self, partition_id: str, *, now: datetime
    ) -> tuple[ObservationPartitionPin, ...]: ...

    async def retention_permitted(
        self, partition: ObservationPartition, *, now: datetime
    ) -> bool: ...

    async def active_holds(
        self, manifest_digest: str, *, now: datetime
    ) -> tuple[RetentionHold, ...]: ...

    async def build_checkpoint(
        self, partition: ObservationPartition, *, now: datetime
    ) -> ObservationCheckpoint: ...

    async def archive_records(self, partition_id: str) -> tuple[Mapping[str, object], ...]: ...

    async def transition(
        self,
        partition: ObservationPartition,
        target: ObservationPartitionState,
        *,
        reason: str,
        evidence_refs: tuple[str, ...],
        recorded_at: datetime,
    ) -> None: ...


class OperationalHistoryLifecycleRunner:
    """Coordinate lifecycle contracts while keeping purge behind two explicit gates."""

    def __init__(
        self,
        *,
        config: OperationalHistoryLifecycleRunnerConfig,
        repository: OperationalHistoryLifecycleRepository,
        history: PostgresOperationalHistoryStore,
        archives: PostgresOperationalArchiveStore,
        artifacts: AzureBlobOperationalHistoryArtifactStore,
    ) -> None:
        self._config = config
        self._repository = repository
        self._history = history
        self._archives = archives
        self._artifacts = artifacts
        self._writer = OperationalHistoryArchiveWriter(
            artifacts=artifacts,
            metadata=history,
            manifests=archives,
        )
        self._reader = OperationalHistoryArchiveReader(
            artifacts=artifacts,
            metadata=history,
        )
        self._purger = OperationalArchivePurgeCoordinator(
            receipts=archives,
            source=history,
        )

    async def run_once(self, *, now: datetime) -> OperationalHistoryLifecycleRunResult:
        """Run one bounded pass; shadow performs no database or Blob mutation."""

        if now.tzinfo is None:
            raise ValueError("operational history lifecycle time MUST be timezone-aware")
        pressure = await self._repository.assess_pressure(self._pressure_policy())
        if self._config.mode is not OperationalHistoryLifecycleMode.SHADOW:
            await self._history.write_storage_pressure(pressure, observed_at=now)
        planned: list[str] = []
        applied: list[str] = []
        blocked: list[str] = []
        partitions = await self._repository.list_partitions(
            limit=self._config.max_partitions,
            now=now,
        )
        for partition in partitions:
            action, checkpoint, manifest, verification, restore = await self._plan(
                partition,
                pressure=pressure,
                now=now,
            )
            key = f"{partition.partition_id}:{action.value}"
            planned.append(key)
            if self._config.mode is OperationalHistoryLifecycleMode.SHADOW:
                continue
            if action in {
                OperationalHistoryLifecycleAction.HOLD,
                OperationalHistoryLifecycleAction.NONE,
            }:
                blocked.append(key)
                continue
            if (
                action is OperationalHistoryLifecycleAction.PURGE
                and self._config.mode is not OperationalHistoryLifecycleMode.CERTIFY
            ):
                blocked.append(f"{key}:certify_mode_required")
                continue
            changed = await self._apply(
                partition,
                action,
                checkpoint=checkpoint,
                manifest=manifest,
                verification=verification,
                restore=restore,
                now=now,
            )
            (applied if changed else blocked).append(key)
        return OperationalHistoryLifecycleRunResult(
            mode=self._config.mode,
            planned=tuple(planned),
            applied=tuple(applied),
            blocked=tuple(blocked),
        )

    async def _plan(
        self,
        partition: ObservationPartition,
        *,
        pressure: StoragePressureAssessment,
        now: datetime,
    ) -> tuple[
        OperationalHistoryLifecycleAction,
        ObservationCheckpoint | None,
        ArchiveManifest | None,
        ArchiveVerificationReceipt | None,
        ArchiveRestoreReceipt | None,
    ]:
        checkpoint = await self._repository.latest_checkpoint(partition.partition_id)
        manifest = await self._repository.latest_manifest(partition.partition_id)
        verification = (
            await self._repository.latest_verification(manifest.digest)
            if manifest is not None
            else None
        )
        restore = (
            await self._repository.latest_restore(manifest.digest) if manifest is not None else None
        )
        evidence = OperationalHistoryLifecycleEvidence(
            checkpoint=checkpoint,
            archive_written=manifest is not None,
            archive_verified=verification is not None and verification.verified,
            restore_passed=restore is not None and restore.passed,
            retention_permitted=await self._repository.retention_permitted(partition, now=now),
            correction_closed=partition.state is not ObservationPartitionState.CORRECTION_PENDING,
            pins=await self._repository.active_pins(partition.partition_id, now=now),
        )
        decision = plan_operational_history_lifecycle(
            partition,
            evidence,
            pressure,
            now=now,
        )
        return decision.action, checkpoint, manifest, verification, restore

    async def _apply(
        self,
        partition: ObservationPartition,
        action: OperationalHistoryLifecycleAction,
        *,
        checkpoint: ObservationCheckpoint | None,
        manifest: ArchiveManifest | None,
        verification: ArchiveVerificationReceipt | None,
        restore: ArchiveRestoreReceipt | None,
        now: datetime,
    ) -> bool:
        if action is OperationalHistoryLifecycleAction.SEAL:
            await self._transition(partition, ObservationPartitionState.SEALED, action, (), now)
            return True
        if action is OperationalHistoryLifecycleAction.CHECKPOINT:
            if checkpoint is None or not checkpoint.valid:
                checkpoint = await self._repository.build_checkpoint(partition, now=now)
                await self._history.append_checkpoint(checkpoint)
            if not checkpoint.valid:
                return False
            await self._transition(
                partition,
                ObservationPartitionState.CHECKPOINTED,
                action,
                (checkpoint.digest,),
                now,
            )
            return True
        if action is OperationalHistoryLifecycleAction.ARCHIVE:
            if checkpoint is None or not checkpoint.valid:
                return False
            records = await self._repository.archive_records(partition.partition_id)
            manifest = manifest or _build_manifest(partition, checkpoint, records, now=now)
            artifact = await self._writer.write(
                manifest,
                records,
                scope_refs=(partition.scope_ref,),
                allowed_purposes=(_PURPOSE,),
            )
            await self._transition(
                partition,
                ObservationPartitionState.ARCHIVED,
                action,
                (manifest.digest, artifact.digest),
                now,
            )
            return True
        if action is OperationalHistoryLifecycleAction.VERIFY:
            if manifest is None:
                return False
            if verification is not None and verification.verified:
                await self._transition(
                    partition,
                    ObservationPartitionState.VERIFIED,
                    action,
                    (verification.digest,),
                    now,
                )
                return True
            verification_receipt = await self._verify(manifest, now=now)
            await self._archives.append_verification(verification_receipt)
            if not verification_receipt.verified:
                return False
            await self._transition(
                partition,
                ObservationPartitionState.VERIFIED,
                action,
                (verification_receipt.digest,),
                now,
            )
            return True
        if action is OperationalHistoryLifecycleAction.RESTORE_SAMPLE:
            if manifest is None or verification is None:
                return False
            restore_receipt = await self._restore(manifest, verification, now=now)
            await self._archives.append_restore(restore_receipt)
            return restore_receipt.passed
        if action is OperationalHistoryLifecycleAction.MARK_PURGE_ELIGIBLE:
            if restore is None or not restore.passed:
                return False
            await self._transition(
                partition,
                ObservationPartitionState.PURGE_ELIGIBLE,
                action,
                (restore.digest,),
                now,
            )
            return True
        if action is OperationalHistoryLifecycleAction.PURGE:
            return await self._purge(
                partition,
                manifest=manifest,
                verification=verification,
                restore=restore,
                now=now,
            )
        return False

    async def _verify(
        self,
        manifest: ArchiveManifest,
        *,
        now: datetime,
    ) -> ArchiveVerificationReceipt:
        artifact = await self._history.get_archive_artifact(manifest.digest)
        content = None if artifact is None else await self._artifacts.get(artifact.storage_ref)
        payload = _archive_payload(content)
        return verify_archive_manifest(
            manifest,
            observed_archive_content_digest=_bytes_digest(content or b""),
            observed_source_partition_digests=_string_tuple(
                payload.get("source_partition_digests")
            ),
            observed_source_schema_versions=manifest.source_schema_versions,
            observed_ontology_release_digests=manifest.ontology_release_digests,
            verified_at=now,
        )

    async def _restore(
        self,
        manifest: ArchiveManifest,
        verification: ArchiveVerificationReceipt,
        *,
        now: datetime,
    ) -> ArchiveRestoreReceipt:
        artifact = await self._history.get_archive_artifact(manifest.digest)
        if artifact is None:
            raise LookupError("operational archive artifact metadata is unavailable")
        archived = await self._reader.read(
            principal=OperationalArchivePrincipal(
                principal_id="system:operational-history-lifecycle",
                purpose=_PURPOSE,
                scope_refs=artifact.scope_refs,
            ),
            manifest_digest=manifest.digest,
        )
        payload = _archive_payload(archived.content)
        records = payload.get("records")
        if not isinstance(records, list):
            records = []
        sampled = tuple(item.content_digest for item in manifest.source_partitions)
        return evaluate_restore_sample(
            manifest,
            verification,
            sampled_partition_digests=sampled,
            observed_partition_digests=_string_tuple(payload.get("source_partition_digests")),
            restored_object_count=_subject_count(records, "object"),
            restored_relationship_count=_subject_count(records, "relationship"),
            failure_code=None,
            sampled_at=now,
        )

    async def _purge(
        self,
        partition: ObservationPartition,
        *,
        manifest: ArchiveManifest | None,
        verification: ArchiveVerificationReceipt | None,
        restore: ArchiveRestoreReceipt | None,
        now: datetime,
    ) -> bool:
        if manifest is None or verification is None or restore is None:
            return False
        holds = await self._repository.active_holds(manifest.digest, now=now)
        retention = evaluate_retention_holds(manifest, holds, evaluated_at=now)
        receipt = await self._purger.purge(
            manifest,
            verification,
            restore,
            retention,
            idempotency_key=f"operational-history:{partition.partition_id}",
            recorded_at=now,
        )
        return receipt.status in {ArchivePurgeStatus.SUCCEEDED, ArchivePurgeStatus.DUPLICATE}

    async def _transition(
        self,
        partition: ObservationPartition,
        target: ObservationPartitionState,
        action: OperationalHistoryLifecycleAction,
        evidence_refs: tuple[str, ...],
        now: datetime,
    ) -> None:
        await self._repository.transition(
            partition,
            target,
            reason=action.value,
            evidence_refs=evidence_refs,
            recorded_at=now,
        )

    def _pressure_policy(self) -> StoragePressurePolicy:
        return StoragePressurePolicy(
            warning_bytes=self._config.warning_bytes,
            critical_bytes=self._config.critical_bytes,
            hard_bytes=self._config.hard_bytes,
            max_purge_backlog=self._config.max_purge_backlog,
            max_projection_lag=self._config.max_projection_lag,
        )


def _build_manifest(
    partition: ObservationPartition,
    checkpoint: ObservationCheckpoint,
    records: Sequence[Mapping[str, object]],
    *,
    now: datetime,
) -> ArchiveManifest:
    payload = {
        "schema_version": "1.0.0",
        "source_partition_digests": [checkpoint.source_digest],
        "records": list(records),
    }
    return build_archive_manifest(
        (
            ArchiveSourcePartition(
                partition_id=partition.partition_id,
                content_digest=checkpoint.source_digest,
                interval_start=partition.interval_start,
                interval_end=partition.interval_end,
                object_count=checkpoint.object_count,
                relationship_count=checkpoint.relationship_count,
                schema_version=_SCHEMA_VERSION,
                ontology_release_digest=checkpoint.ontology_release_digest,
                complete=checkpoint.valid,
                conflict_count=checkpoint.conflicted_count,
            ),
        ),
        archive_content_digest=_bytes_digest(_canonical_archive(payload)),
        compression_profile="none",
        encryption_profile="platform-managed",
        destination_class="private-blob",
        retention_class="operational-history",
        creation_receipt_digest=_json_digest(
            {
                "partition_id": partition.partition_id,
                "checkpoint_id": checkpoint.checkpoint_id,
            }
        ),
        created_at=now,
    )


def _canonical_archive(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        + b"\n"
    )


def _archive_payload(content: bytes | None) -> dict[str, object]:
    if not content:
        return {}
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


async def _run(
    config: OperationalHistoryLifecycleRunnerConfig,
) -> OperationalHistoryLifecycleRunResult:
    repository = PostgresOperationalHistoryLifecycleRepository(dsn=config.dsn)
    history = PostgresOperationalHistoryStore(
        config=PostgresOperationalHistoryConfig(dsn=config.dsn)
    )
    archives = PostgresOperationalArchiveStore(
        config=PostgresOperationalArchiveStoreConfig(dsn=config.dsn)
    )
    async with httpx.AsyncClient() as http_client:
        identity = ManagedIdentityWorkloadIdentity.from_env(
            http_client=http_client,
            client_id_env="FDAI_MI_CLIENT_ID",
        )
        artifacts = AzureBlobOperationalHistoryArtifactStore(
            config=AzureBlobOperationalHistoryConfig(container_url=config.container_url),
            identity=identity,
            http_client=http_client,
        )
        runner = OperationalHistoryLifecycleRunner(
            config=config,
            repository=repository,
            history=history,
            archives=archives,
            artifacts=artifacts,
        )
        return await runner.run_once(now=datetime.now(UTC))


def main(argv: Sequence[str] | None = None) -> int:
    """Run one lifecycle pass and map fail-closed errors to a stable exit code."""

    parser = argparse.ArgumentParser(prog="fdai-operational-history-lifecycle")
    parser.add_argument(
        "--mode",
        choices=tuple(item.value for item in OperationalHistoryLifecycleMode),
    )
    parser.add_argument("--authority-receipt-digest")
    args = parser.parse_args(tuple(argv) if argv is not None else None)
    logging.basicConfig(level=os.environ.get("FDAI_LOG_LEVEL", "INFO"))
    try:
        mode = None if args.mode is None else OperationalHistoryLifecycleMode(str(args.mode))
        config = OperationalHistoryLifecycleRunnerConfig.from_env(
            os.environ,
            mode=mode,
            authority_receipt_digest=args.authority_receipt_digest,
        )
        result = asyncio.run(_run(config))
    except (ValueError, LookupError, RuntimeError, OSError, psycopg.Error, httpx.HTTPError):
        _LOGGER.exception("operational_history_lifecycle_failed")
        return 3
    print(json.dumps(result.as_record(), sort_keys=True))
    return 0


def _subject_count(records: Sequence[object], subject_kind: str) -> int:
    return sum(
        isinstance(item, Mapping) and item.get("subject_kind") == subject_kind for item in records
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        return ()
    return tuple(str(item) for item in value)


def _bounded_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name, "").strip()
    try:
        return default if not raw else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} MUST be an integer") from exc


def _optional(value: str | None) -> str | None:
    normalized = "" if value is None else value.strip()
    return normalized or None


def _json_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _bytes_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _is_digest(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _canonical_digest(value: str | None, name: str) -> None:
    if value is None or not _is_digest(value):
        raise ValueError(f"operational history {name} MUST be a canonical SHA-256 digest")


if __name__ == "__main__":
    sys.exit(main())
