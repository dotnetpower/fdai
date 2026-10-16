"""Explicit unavailable bindings for self-health sources not yet composed by a venue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fdai_service_contracts.self_health import (
    OperationalStateFieldName,
    OperationalStateFieldV1,
    SelfHealthSignalName,
)

from fdai.core.readiness.self_health import SelfHealthCatalog
from fdai.core.readiness.self_health_runtime import SelfHealthExporterRegistry
from fdai.shared.providers.self_health import (
    SelfHealthExporterUnavailableError,
    SelfHealthExportSample,
)


@dataclass(frozen=True, slots=True)
class UnavailableSelfHealthExporter:
    """Named fail-closed binding used until the accountable source is composed."""

    signal: SelfHealthSignalName
    metric: str
    exporter_id: str

    async def observe(self, *, now: datetime) -> SelfHealthExportSample:
        del now
        raise SelfHealthExporterUnavailableError(self.signal.value)


@dataclass(frozen=True, slots=True)
class UnavailableOperationalStateExporter:
    """Named unavailable field binding; it never fabricates current state."""

    field_name: OperationalStateFieldName
    exporter_id: str
    maximum_age_seconds: int = 60

    async def observe(self, *, now: datetime) -> OperationalStateFieldV1:
        del now
        raise SelfHealthExporterUnavailableError(self.field_name.value)


def unavailable_self_health_registry(catalog: SelfHealthCatalog) -> SelfHealthExporterRegistry:
    """Return complete explicit unavailable bindings, never success-shaped defaults."""

    return SelfHealthExporterRegistry(
        catalog=catalog,
        signal_exporters={
            signal: UnavailableSelfHealthExporter(
                signal=signal,
                metric=catalog.policies[signal].metric,
                exporter_id=f"unavailable:self-health:{signal.value}",
            )
            for signal in SelfHealthSignalName
        },
        state_exporters={
            field_name: UnavailableOperationalStateExporter(
                field_name=field_name,
                exporter_id=f"unavailable:operational-state:{field_name.value}",
            )
            for field_name in OperationalStateFieldName
        },
    )


__all__ = [
    "UnavailableOperationalStateExporter",
    "UnavailableSelfHealthExporter",
    "unavailable_self_health_registry",
]
