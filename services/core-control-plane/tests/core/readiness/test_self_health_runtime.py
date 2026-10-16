from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.readiness.self_health import load_self_health_catalog
from fdai.core.readiness.self_health_runtime import (
    OPERATIONAL_STATE_KEY,
    SelfHealthExporterRegistry,
    SelfHealthExporterRegistryError,
    SelfHealthRuntimeMonitor,
)
from fdai.shared.providers.self_health import (
    SelfHealthExporterUnavailableError,
    SelfHealthExportSample,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.self_health import (
    OperationalStateFieldName,
    OperationalStateFieldStatus,
    OperationalStateFieldV1,
    SelfHealthSignalName,
    SelfHealthSignalStatus,
)

ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 10, 18, tzinfo=UTC)


def _digest(character: str) -> str:
    return "sha256:" + (character * 64)


def _catalog():
    matrix = load_matrix_from_yaml(ROOT / "config" / "notifications-matrix.yaml")
    return load_self_health_catalog(
        ROOT / "config" / "self-health-signals.yaml",
        route_fallbacks={name: route.on_all_fail.value for name, route in matrix.routes.items()},
    )


@dataclass(frozen=True)
class _SignalExporter:
    signal: SelfHealthSignalName
    metric: str
    exporter_id: str
    unavailable: bool = False

    async def observe(self, *, now: datetime) -> SelfHealthExportSample:
        if self.unavailable:
            raise SelfHealthExporterUnavailableError(self.signal.value)
        return SelfHealthExportSample(
            signal=self.signal,
            value=_catalog().policies[self.signal].threshold,
            observed_at=now,
            source=self.exporter_id,
        )


@dataclass(frozen=True)
class _FieldExporter:
    field_name: OperationalStateFieldName
    exporter_id: str
    maximum_age_seconds: int = 300

    async def observe(self, *, now: datetime) -> OperationalStateFieldV1:
        return OperationalStateFieldV1(
            name=self.field_name,
            status=OperationalStateFieldStatus.AVAILABLE,
            value_digest=_digest("a"),
            source=self.exporter_id,
            observed_at=now,
            maximum_age_seconds=self.maximum_age_seconds,
            fresh=True,
            reason="current",
        )


def _registry(*, unavailable: SelfHealthSignalName | None = None):
    catalog = _catalog()
    return SelfHealthExporterRegistry(
        catalog=catalog,
        signal_exporters={
            signal: _SignalExporter(
                signal=signal,
                metric=catalog.policies[signal].metric,
                exporter_id=f"runtime:{signal.value}",
                unavailable=signal is unavailable,
            )
            for signal in SelfHealthSignalName
        },
        state_exporters={
            field_name: _FieldExporter(
                field_name=field_name,
                exporter_id=f"runtime-state:{field_name.value}",
            )
            for field_name in OperationalStateFieldName
        },
    )


async def test_complete_registry_persists_authority_neutral_operational_state() -> None:
    store = InMemoryStateStore()
    monitor = SelfHealthRuntimeMonitor(
        registry=_registry(unavailable=SelfHealthSignalName.VERIFIER_FAILURE_RATE),
        store=store,
    )

    snapshot = await monitor.collect_and_persist(now=NOW)
    persisted = await store.read_state(OPERATIONAL_STATE_KEY)

    assert len(snapshot.self_health.signals) == 15
    assert len(snapshot.fields) == 8
    verifier = next(
        item
        for item in snapshot.self_health.signals
        if item.signal is SelfHealthSignalName.VERIFIER_FAILURE_RATE
    )
    assert verifier.status is SelfHealthSignalStatus.UNAVAILABLE
    assert verifier.alert is True
    assert snapshot.execution_authority is False
    assert persisted is not None
    assert persisted["snapshot"]["snapshot_digest"] == snapshot.snapshot_digest
    assert await store.verify_chain()


def test_registry_rejects_missing_signal_or_state_exporter() -> None:
    complete = _registry()
    signal_exporters = dict(complete.signal_exporters)
    signal_exporters.pop(SelfHealthSignalName.DLQ_DEPTH)

    with pytest.raises(SelfHealthExporterRegistryError, match="coverage"):
        SelfHealthExporterRegistry(
            catalog=complete.catalog,
            signal_exporters=signal_exporters,
            state_exporters=complete.state_exporters,
        )
