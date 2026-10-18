"""Complete self-health exporter registry and durable operational-state snapshot."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime

from fdai_service_contracts.self_health import (
    OperationalStateFieldName,
    OperationalStateFieldStatus,
    OperationalStateFieldV1,
    OperationalStateSnapshotV1,
    SelfHealthSignalName,
    SelfHealthSignalStateV1,
    SelfHealthSignalStatus,
    SelfHealthSnapshotV1,
    operational_state_snapshot_digest,
    self_health_snapshot_digest,
)

from fdai.core.readiness.self_health import (
    SelfHealthCatalog,
    SelfHealthObservation,
    SelfHealthSignalPolicy,
)
from fdai.shared.providers.self_health import (
    OperationalStateFieldExporter,
    SelfHealthExporter,
    SelfHealthExporterUnavailableError,
)
from fdai.shared.providers.state_store import StateStore

OPERATIONAL_STATE_KEY = "runtime:operational-state"


class SelfHealthExporterRegistryError(ValueError):
    """Raised when exporter ownership or metric identity is incomplete."""


class SelfHealthExporterRegistry:
    """Exact accountable exporter bindings for every self-health signal and state field."""

    def __init__(
        self,
        *,
        catalog: SelfHealthCatalog,
        signal_exporters: Mapping[SelfHealthSignalName, SelfHealthExporter],
        state_exporters: Mapping[OperationalStateFieldName, OperationalStateFieldExporter],
    ) -> None:
        if set(signal_exporters) != set(SelfHealthSignalName):
            raise SelfHealthExporterRegistryError(
                "self-health signal exporter coverage MUST be complete"
            )
        if set(state_exporters) != set(OperationalStateFieldName):
            raise SelfHealthExporterRegistryError(
                "operational state exporter coverage MUST be complete"
            )
        exporter_ids: list[str] = []
        for signal, exporter in signal_exporters.items():
            policy = catalog.policies[signal]
            if (
                exporter.signal is not signal
                or exporter.metric != policy.metric
                or not exporter.exporter_id
                or exporter.exporter_id != exporter.exporter_id.strip()
            ):
                raise SelfHealthExporterRegistryError(
                    f"self-health exporter identity mismatch: {signal.value}"
                )
            exporter_ids.append(exporter.exporter_id)
        for field_name, state_exporter in state_exporters.items():
            if (
                state_exporter.field_name is not field_name
                or not state_exporter.exporter_id
                or state_exporter.exporter_id != state_exporter.exporter_id.strip()
                or state_exporter.maximum_age_seconds < 1
            ):
                raise SelfHealthExporterRegistryError(
                    f"operational state exporter identity mismatch: {field_name.value}"
                )
            exporter_ids.append(state_exporter.exporter_id)
        if len(set(exporter_ids)) != len(exporter_ids):
            raise SelfHealthExporterRegistryError("runtime exporter ids MUST be unique")
        self.catalog = catalog
        self.signal_exporters = dict(signal_exporters)
        self.state_exporters = dict(state_exporters)


class SelfHealthRuntimeMonitor:
    """Collect every exporter once and persist one no-authority authorized-read snapshot."""

    def __init__(
        self,
        *,
        registry: SelfHealthExporterRegistry,
        store: StateStore,
        timeout_seconds: float = 2.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("self-health exporter timeout MUST be positive")
        self._registry = registry
        self._store = store
        self._timeout_seconds = timeout_seconds

    async def collect_and_persist(self, *, now: datetime) -> OperationalStateSnapshotV1:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("self-health collection time MUST be timezone-aware")
        signal_states = await asyncio.gather(
            *(
                self._signal_state(signal, exporter, now=now)
                for signal, exporter in sorted(
                    self._registry.signal_exporters.items(),
                    key=lambda item: item[0].value,
                )
            )
        )
        field_states = await asyncio.gather(
            *(
                self._field_state(field_name, exporter, now=now)
                for field_name, exporter in sorted(
                    self._registry.state_exporters.items(),
                    key=lambda item: item[0].value,
                )
            )
        )
        self_health = SelfHealthSnapshotV1(
            catalog_version=self._registry.catalog.version,
            generated_at=now,
            signals=tuple(signal_states),
            snapshot_digest=self_health_snapshot_digest(
                catalog_version=self._registry.catalog.version,
                generated_at=now,
                signals=tuple(signal_states),
            ),
        )
        snapshot = OperationalStateSnapshotV1(
            generated_at=now,
            self_health=self_health,
            fields=tuple(field_states),
            snapshot_digest=operational_state_snapshot_digest(
                generated_at=now,
                self_health=self_health,
                fields=tuple(field_states),
            ),
        )
        await self._persist(snapshot)
        return snapshot

    async def _signal_state(
        self,
        signal: SelfHealthSignalName,
        exporter: SelfHealthExporter,
        *,
        now: datetime,
    ) -> SelfHealthSignalStateV1:
        policy = self._registry.catalog.policies[signal]
        try:
            sample = await asyncio.wait_for(
                exporter.observe(now=now),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            return _unavailable_signal(policy, exporter.exporter_id, now, "exporter_timeout")
        except SelfHealthExporterUnavailableError as exc:
            return _unavailable_signal(policy, exporter.exporter_id, now, exc.reason)
        if sample.signal is not signal or sample.source != exporter.exporter_id:
            raise SelfHealthExporterRegistryError(
                f"self-health exporter returned another identity: {signal.value}"
            )
        observation = SelfHealthObservation(
            signal=signal,
            value=sample.value,
            observed_at=sample.observed_at,
            source=sample.source,
        )
        decision = self._registry.catalog.evaluate(observation, now=now)
        return SelfHealthSignalStateV1(
            signal=signal,
            metric=policy.metric,
            exporter_id=exporter.exporter_id,
            status=(
                SelfHealthSignalStatus.ALERT if decision.alert else SelfHealthSignalStatus.HEALTHY
            ),
            value=observation.value,
            observed_at=observation.observed_at,
            recorded_at=now,
            maximum_age_seconds=policy.maximum_age_seconds,
            fresh=decision.reason not in {"observation_stale", "observation_from_future"},
            reason=decision.reason,
            route=decision.route,
            fallback=decision.fallback,
            alert=decision.alert,
        )

    async def _field_state(
        self,
        field_name: OperationalStateFieldName,
        exporter: OperationalStateFieldExporter,
        *,
        now: datetime,
    ) -> OperationalStateFieldV1:
        try:
            field = await asyncio.wait_for(
                exporter.observe(now=now),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            return _unavailable_field(
                field_name,
                exporter.exporter_id,
                exporter.maximum_age_seconds,
                "exporter_timeout",
            )
        except SelfHealthExporterUnavailableError as exc:
            return _unavailable_field(
                field_name,
                exporter.exporter_id,
                exporter.maximum_age_seconds,
                exc.reason,
            )
        if field.name is not field_name or field.source != exporter.exporter_id:
            raise SelfHealthExporterRegistryError(
                f"operational state exporter returned another identity: {field_name.value}"
            )
        if field.maximum_age_seconds != exporter.maximum_age_seconds:
            raise SelfHealthExporterRegistryError(
                f"operational state exporter freshness mismatch: {field_name.value}"
            )
        return field

    async def _persist(self, snapshot: OperationalStateSnapshotV1) -> None:
        current = await self._store.read_state(OPERATIONAL_STATE_KEY)
        if current is not None:
            revision_raw = current.get("revision")
            snapshot_raw = current.get("snapshot")
            if (
                isinstance(revision_raw, bool)
                or not isinstance(revision_raw, int)
                or revision_raw < 1
                or not isinstance(snapshot_raw, Mapping)
            ):
                raise RuntimeError("operational state durable record is malformed")
            try:
                retained = OperationalStateSnapshotV1.model_validate(snapshot_raw)
            except ValueError as exc:
                raise RuntimeError("operational state durable record is malformed") from exc
            if retained == snapshot:
                return
            revision = revision_raw
        else:
            revision = 0
        value = {
            "revision": revision + 1,
            "snapshot": snapshot.model_dump(mode="json"),
        }
        audit = {
            "actor": "Saga",
            "action_kind": "runtime.operational-state-recorded",
            "snapshot_digest": snapshot.snapshot_digest,
            "self_health_snapshot_digest": snapshot.self_health.snapshot_digest,
            "generated_at": snapshot.generated_at.isoformat(),
            "execution_authority": False,
        }
        if current is None:
            changed = await self._store.write_state_with_audit_if_absent(
                OPERATIONAL_STATE_KEY,
                value,
                audit,
            )
        else:
            changed = await self._store.compare_and_set_state_with_audit(
                OPERATIONAL_STATE_KEY,
                value,
                expected_revision=revision,
                audit_entry=audit,
            )
        if not changed:
            winner = await self._store.read_state(OPERATIONAL_STATE_KEY)
            if winner is None or winner.get("snapshot") != snapshot.model_dump(mode="json"):
                raise RuntimeError("operational state snapshot CAS conflict")


def _unavailable_signal(
    policy: SelfHealthSignalPolicy,
    exporter_id: str,
    now: datetime,
    reason: str,
) -> SelfHealthSignalStateV1:
    return SelfHealthSignalStateV1(
        signal=policy.signal,
        metric=policy.metric,
        exporter_id=exporter_id,
        status=SelfHealthSignalStatus.UNAVAILABLE,
        value=None,
        observed_at=None,
        recorded_at=now,
        maximum_age_seconds=policy.maximum_age_seconds,
        fresh=False,
        reason=reason,
        route=policy.route,
        fallback=policy.fallback,
        alert=True,
    )


def _unavailable_field(
    field_name: OperationalStateFieldName,
    exporter_id: str,
    maximum_age_seconds: int,
    reason: str,
) -> OperationalStateFieldV1:
    return OperationalStateFieldV1(
        name=field_name,
        status=OperationalStateFieldStatus.UNAVAILABLE,
        value_digest=None,
        source=exporter_id,
        observed_at=None,
        maximum_age_seconds=maximum_age_seconds,
        fresh=False,
        reason=reason,
    )


__all__ = [
    "OPERATIONAL_STATE_KEY",
    "SelfHealthExporterRegistry",
    "SelfHealthExporterRegistryError",
    "SelfHealthRuntimeMonitor",
]
