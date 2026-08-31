"""Persist analyzer Pod lifecycle receipts as a retained operator projection.

The analyzer tick is the only component that observes a finding, its canonical
assessment, and the outcome of its publication together. That join is exactly
what an operator surface needs, and it disappears when the process exits, so
this recorder writes it to tracked state before the tick reports success.

Two properties matter more than convenience here:

- **Failure history survives.** Records are merged with what was already
  retained, so a later tick that observes a healthy Pod adds an observation
  instead of erasing the failures that preceded it. Retention stays bounded,
  and a repeated window key replaces its older copy rather than counting twice.
- **A write failure fails the tick.** A projection nobody could persist is not
  a projection an operator may read as current. The recorder raises, the tick
  reports failure, and the surface keeps serving the previous state with its
  own staleness gap rather than a silently frozen one.

Only Kubernetes Pod findings are projected. Threshold analyzers carry no Pod
lifecycle classification, and a receipt without one cannot be reduced into a
current state, a failure, or a recovery.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta

from fdai.core.investigation.kubernetes_pod import KIND_KUBERNETES_POD
from fdai.core.ontology_platform.kubernetes_pod_recovery_evidence import (
    KubernetesPodRecoveryStatus,
)
from fdai.core.ontology_platform.kubernetes_pod_replacement_evidence import (
    KubernetesPodReplacementStatus,
)
from fdai.core.readiness.detection_lifecycle import (
    DEFAULT_LIFECYCLE_FRESHNESS,
    DEFAULT_LIFECYCLE_RETENTION,
    DETECTION_LIFECYCLE_SCHEMA_VERSION,
    DetectionPublicationState,
    PodLifecycleDetectionRecord,
    PodLifecycleDetectionSnapshot,
    pod_lifecycle_detection_state_key,
    reduce_pod_lifecycle_detection,
    retain_pod_lifecycle_records,
)
from fdai.delivery.analyzer_tick import AnalyzerFindingReceipt, AnalyzerTickReport
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)

_RECORDS_FIELD = "records"
_SNAPSHOT_FIELD = "snapshot"


class DetectionLifecycleRecordError(RuntimeError):
    """The Pod lifecycle projection could not be read or persisted."""


def pod_lifecycle_record(
    receipt: AnalyzerFindingReceipt,
    *,
    recorded_at: datetime,
) -> PodLifecycleDetectionRecord | None:
    """Return the retained record for one Pod receipt, else ``None``.

    A receipt whose signal is not a canonical Pod lifecycle classification is
    not a Pod observation this projection can speak about, so it is skipped
    rather than coerced into an unknown lifecycle state.
    """

    if receipt.resource_kind != KIND_KUBERNETES_POD:
        return None
    try:
        signal = KubernetesPodReplacementStatus(receipt.signal)
    except ValueError:
        return None
    recovery_status: KubernetesPodRecoveryStatus | None = None
    if receipt.recovery_status is not None:
        try:
            recovery_status = KubernetesPodRecoveryStatus(receipt.recovery_status)
        except ValueError as exc:
            raise DetectionLifecycleRecordError(
                f"unknown Pod recovery status {receipt.recovery_status!r}"
            ) from exc
    occurred_at = receipt.occurred_at.astimezone(UTC)
    return PodLifecycleDetectionRecord(
        resource_ref=receipt.resource_ref,
        idempotency_key=receipt.idempotency_key,
        signal=signal,
        occurred_at=occurred_at,
        recorded_at=max(recorded_at.astimezone(UTC), occurred_at),
        detection_latency_seconds=max(receipt.detection_latency_seconds, 0.0),
        evidence_complete=receipt.evidence_complete,
        recovery_closed=receipt.recovery_closed,
        recovery_status=recovery_status,
        publication=DetectionPublicationState(receipt.publication.value),
        assessed_by=receipt.assessed_by,
        evidence_refs=receipt.evidence_refs,
        evidence_gaps=receipt.evidence_gaps,
    )


class DetectionLifecycleRecorder:
    """Merge, bound, reduce, and persist one target's lifecycle projection."""

    __slots__ = ("_freshness_budget", "_retention", "_state_store")

    def __init__(
        self,
        state_store: StateStore,
        *,
        retention: int = DEFAULT_LIFECYCLE_RETENTION,
        freshness_budget: timedelta = DEFAULT_LIFECYCLE_FRESHNESS,
    ) -> None:
        if retention < 1:
            raise ValueError("Pod lifecycle retention MUST be positive")
        if freshness_budget <= timedelta(0):
            raise ValueError("Pod lifecycle freshness budget MUST be positive")
        self._state_store = state_store
        self._retention = retention
        self._freshness_budget = freshness_budget

    async def record_report(
        self,
        report: AnalyzerTickReport,
        *,
        at: datetime,
    ) -> tuple[PodLifecycleDetectionSnapshot, ...]:
        """Persist every Pod target the tick observed and return its projection."""

        return await self.record_receipts(report.receipts, at=at)

    async def record_receipts(
        self,
        receipts: Sequence[AnalyzerFindingReceipt],
        *,
        at: datetime,
    ) -> tuple[PodLifecycleDetectionSnapshot, ...]:
        """Persist the projection for every Pod target present in ``receipts``."""

        observed: dict[str, list[PodLifecycleDetectionRecord]] = {}
        for receipt in receipts:
            record = pod_lifecycle_record(receipt, recorded_at=at)
            if record is None:
                continue
            observed.setdefault(record.resource_ref, []).append(record)

        snapshots: list[PodLifecycleDetectionSnapshot] = []
        for resource_ref in sorted(observed):
            snapshots.append(
                await self._persist(resource_ref, tuple(observed[resource_ref]), at=at)
            )
        return tuple(snapshots)

    async def read_snapshot(self, resource_ref: str) -> PodLifecycleDetectionSnapshot | None:
        """Return the persisted projection for ``resource_ref``, else ``None``."""

        key = pod_lifecycle_detection_state_key(resource_ref)
        stored = await self._read(key)
        if stored is None:
            return None
        raw = stored.get(_SNAPSHOT_FIELD)
        if not isinstance(raw, dict):
            raise DetectionLifecycleRecordError(
                f"tracked Pod lifecycle state {key!r} carries no projection"
            )
        return PodLifecycleDetectionSnapshot.model_validate(raw)

    async def _persist(
        self,
        resource_ref: str,
        observed: tuple[PodLifecycleDetectionRecord, ...],
        *,
        at: datetime,
    ) -> PodLifecycleDetectionSnapshot:
        key = pod_lifecycle_detection_state_key(resource_ref)
        retained = retain_pod_lifecycle_records(
            (*self._retained_records(await self._read(key), key=key), *observed),
            resource_ref=resource_ref,
            retention=self._retention,
        )
        snapshot = reduce_pod_lifecycle_detection(
            retained,
            resource_ref=resource_ref,
            generated_at=at.astimezone(UTC),
            freshness_budget=self._freshness_budget,
            retention=self._retention,
        )
        value = {
            "schema_version": DETECTION_LIFECYCLE_SCHEMA_VERSION,
            "resource_ref": resource_ref,
            _SNAPSHOT_FIELD: snapshot.model_dump(mode="json"),
            _RECORDS_FIELD: [record.model_dump(mode="json") for record in retained],
        }
        try:
            await self._state_store.write_state(key, value)
        except Exception as exc:  # noqa: BLE001 - an unpersisted projection MUST fail the tick
            _LOGGER.warning(
                "detection_lifecycle_write_failed",
                extra={"resource_ref": resource_ref, "error": f"{type(exc).__name__}:{exc}"},
            )
            raise DetectionLifecycleRecordError(
                f"Pod lifecycle projection for {resource_ref!r} was not persisted"
            ) from exc
        return snapshot

    async def _read(self, key: str) -> dict[str, object] | None:
        try:
            stored = await self._state_store.read_state(key)
        except Exception as exc:  # noqa: BLE001 - an unreadable history MUST NOT be replaced
            _LOGGER.warning(
                "detection_lifecycle_read_failed",
                extra={"key": key, "error": f"{type(exc).__name__}:{exc}"},
            )
            raise DetectionLifecycleRecordError(
                f"tracked Pod lifecycle state {key!r} could not be read"
            ) from exc
        return dict(stored) if stored is not None else None

    def _retained_records(
        self,
        stored: dict[str, object] | None,
        *,
        key: str,
    ) -> tuple[PodLifecycleDetectionRecord, ...]:
        if stored is None:
            return ()
        version = stored.get("schema_version")
        if version != DETECTION_LIFECYCLE_SCHEMA_VERSION:
            raise DetectionLifecycleRecordError(
                f"tracked Pod lifecycle state {key!r} has unsupported schema {version!r}"
            )
        raw = stored.get(_RECORDS_FIELD)
        if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
            raise DetectionLifecycleRecordError(
                f"tracked Pod lifecycle state {key!r} carries no retained records"
            )
        return tuple(PodLifecycleDetectionRecord.model_validate(item) for item in raw)


__all__ = [
    "DetectionLifecycleRecordError",
    "DetectionLifecycleRecorder",
    "pod_lifecycle_record",
]
