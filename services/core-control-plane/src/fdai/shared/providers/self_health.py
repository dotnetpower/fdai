"""Source seams for complete FDAI self-health and operational state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from fdai_service_contracts.model_provider_health import (
    ModelProviderObservationV1,
    ModelProviderRegistrationV1,
    ModelProviderScopeSnapshotV1,
)
from fdai_service_contracts.self_health import (
    OperationalStateFieldName,
    OperationalStateFieldV1,
    SelfHealthSignalName,
)


class SelfHealthExporterUnavailableError(RuntimeError):
    """A configured exporter cannot provide a current source observation."""

    def __init__(self, message: str = "", *, reason: str = "exporter_unavailable") -> None:
        if reason not in {
            "exporter_unavailable",
            "source_missing",
            "source_malformed",
            "source_unreachable",
            "source_incomplete",
            "source_stale",
            "source_from_future",
        }:
            raise ValueError("self-health unavailable reason MUST be a bounded source code")
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SelfHealthExportSample:
    """One source-authenticated numeric observation before policy evaluation."""

    signal: SelfHealthSignalName
    value: Decimal
    observed_at: datetime
    source: str


class SelfHealthExporter(Protocol):
    """Export one exact catalog metric from its accountable runtime source."""

    @property
    def signal(self) -> SelfHealthSignalName: ...

    @property
    def metric(self) -> str: ...

    @property
    def exporter_id(self) -> str: ...

    async def observe(self, *, now: datetime) -> SelfHealthExportSample: ...


class ModelProviderObservationSource(Protocol):
    @property
    def role(self) -> str: ...

    @property
    def binding_digest(self) -> str: ...

    async def observe(self, *, now: datetime) -> ModelProviderObservationV1: ...


@runtime_checkable
class ModelProviderObservedProvider(Protocol):
    """A provider exposes typed sub-scope evidence, never the global adapter signal."""

    def model_provider_observations(
        self, *, maximum_age_seconds: int
    ) -> ModelProviderObservationSource: ...


class ModelProviderScopeSource(Protocol):
    @property
    def registration(self) -> ModelProviderRegistrationV1: ...

    async def observe(
        self, *, now: datetime, parent_snapshot_digest: str
    ) -> ModelProviderScopeSnapshotV1: ...


class OperationalStateFieldExporter(Protocol):
    """Export one sanitized field for the authorized runtime-state surface."""

    @property
    def field_name(self) -> OperationalStateFieldName: ...

    @property
    def exporter_id(self) -> str: ...

    @property
    def maximum_age_seconds(self) -> int: ...

    async def observe(self, *, now: datetime) -> OperationalStateFieldV1: ...


__all__ = [
    "OperationalStateFieldExporter",
    "SelfHealthExportSample",
    "SelfHealthExporter",
    "SelfHealthExporterUnavailableError",
    "ModelProviderObservationSource",
    "ModelProviderObservedProvider",
    "ModelProviderScopeSource",
]
