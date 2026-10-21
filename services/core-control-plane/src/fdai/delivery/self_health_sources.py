"""Self-health observations from already composed, read-only Core sources."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.self_health import (
    OperationalStateFieldName,
    OperationalStateFieldStatus,
    OperationalStateFieldV1,
    SelfHealthSignalName,
)
from psycopg import Error as DatabaseError

from fdai.core.readiness.self_health import SelfHealthCatalog
from fdai.core.readiness.self_health_runtime import SelfHealthExporterRegistry
from fdai.delivery.self_health_canary import ConsumedCanaryAgeExporter
from fdai.delivery.self_health_exporters import unavailable_self_health_registry
from fdai.shared.providers.self_health import (
    OperationalStateFieldExporter,
    SelfHealthExporter,
    SelfHealthExporterUnavailableError,
    SelfHealthExportSample,
)
from fdai.shared.providers.state_store import StateStore
from fdai.shared.resilience.kill_switch import KILL_SWITCH_STATE_KEY


@dataclass(frozen=True, slots=True)
class RuntimeProbeSelfHealthExporter:
    """Observe the actual listener or the guarded readiness predicate, without probing models."""

    signal: SelfHealthSignalName
    metric: str
    exporter_id: str
    probe: Callable[[datetime], bool]

    async def observe(self, *, now: datetime) -> SelfHealthExportSample:
        return SelfHealthExportSample(
            signal=self.signal,
            value=Decimal(int(self.probe(now))),
            observed_at=now,
            source=self.exporter_id,
        )


@dataclass(frozen=True, slots=True)
class KillSwitchSelfHealthSource:
    store: StateStore

    async def read(self) -> bool:
        """Read the authoritative switch without changing its execution-path cache."""
        try:
            record = await self.store.read_state(KILL_SWITCH_STATE_KEY)
        except (OSError, DatabaseError) as exc:
            raise SelfHealthExporterUnavailableError(reason="source_unreachable") from exc
        if record is None:
            raise SelfHealthExporterUnavailableError(reason="source_missing")
        engaged = record.get("engaged")
        if not isinstance(engaged, bool):
            raise SelfHealthExporterUnavailableError(reason="source_malformed")
        return engaged


@dataclass(frozen=True, slots=True)
class KillSwitchSelfHealthExporter:
    metric: str
    source: KillSwitchSelfHealthSource
    signal: SelfHealthSignalName = SelfHealthSignalName.KILL_SWITCH_STATE
    exporter_id: str = "state-store:kill-switch:signal"

    async def observe(self, *, now: datetime) -> SelfHealthExportSample:
        engaged = await self.source.read()
        return SelfHealthExportSample(
            signal=self.signal,
            value=Decimal(int(engaged)),
            observed_at=now,
            source=self.exporter_id,
        )


@dataclass(frozen=True, slots=True)
class KillSwitchStateExporter:
    source: KillSwitchSelfHealthSource
    field_name: OperationalStateFieldName = OperationalStateFieldName.KILL_SWITCH
    exporter_id: str = "state-store:kill-switch:field"
    maximum_age_seconds: int = 60

    async def observe(self, *, now: datetime) -> OperationalStateFieldV1:
        engaged = await self.source.read()
        return _field(
            self.field_name,
            self.exporter_id,
            self.maximum_age_seconds,
            canonical_digest({"engaged": engaged}),
            now,
        )


@dataclass(frozen=True, slots=True)
class InstalledCoreVersionExporter:
    field_name: OperationalStateFieldName = OperationalStateFieldName.VERSION
    exporter_id: str = "installed-distribution:fdai-core-control-plane"
    maximum_age_seconds: int = 60

    async def observe(self, *, now: datetime) -> OperationalStateFieldV1:
        try:
            installed_version = version("fdai-core-control-plane")
        except PackageNotFoundError as exc:
            raise SelfHealthExporterUnavailableError(reason="source_missing") from exc
        if not installed_version or installed_version != installed_version.strip():
            raise SelfHealthExporterUnavailableError(reason="source_malformed")
        return _field(
            self.field_name,
            self.exporter_id,
            self.maximum_age_seconds,
            canonical_digest(
                {"distribution": "fdai-core-control-plane", "version": installed_version}
            ),
            now,
        )


@dataclass(frozen=True, slots=True)
class RuntimeConfigurationExporter:
    """Identify the policy actually consumed at bootstrap, not desired restart settings."""

    configuration_digest: str
    field_name: OperationalStateFieldName = OperationalStateFieldName.CONFIGURATION
    exporter_id: str = "runtime:policy-consumed-at-bootstrap"
    maximum_age_seconds: int = 60

    async def observe(self, *, now: datetime) -> OperationalStateFieldV1:
        return _field(
            self.field_name,
            self.exporter_id,
            self.maximum_age_seconds,
            self.configuration_digest,
            now,
        )


def runtime_self_health_registry(
    *,
    catalog: SelfHealthCatalog,
    store: StateStore,
    readiness: Callable[[datetime], bool],
    liveness: Callable[[], bool] | None = None,
    runtime_policy: Mapping[str, object] | None = None,
    startup_duration_source: SelfHealthExporter | None = None,
    verifier_health_source: SelfHealthExporter | None = None,
    mixed_model_health_source: SelfHealthExporter | None = None,
    event_lag_source: SelfHealthExporter | None = None,
    canary_result_source: SelfHealthExporter | None = None,
    canary_state_source: OperationalStateFieldExporter | None = None,
) -> SelfHealthExporterRegistry:
    """Bind actual process-owned sources and retain every other unavailable binding."""
    unavailable = unavailable_self_health_registry(catalog)
    signals = dict(unavailable.signal_exporters)
    fields = dict(unavailable.state_exporters)
    age_signal = SelfHealthSignalName.TIME_SINCE_LAST_SUCCESSFUL_CANARY
    signals[age_signal] = ConsumedCanaryAgeExporter(store, catalog.policies[age_signal].metric)
    if startup_duration_source is not None:
        signals[SelfHealthSignalName.COLD_START_DURATION] = startup_duration_source
    if verifier_health_source is not None:
        signals[SelfHealthSignalName.VERIFIER_FAILURE_RATE] = verifier_health_source
    if mixed_model_health_source is not None:
        signals[SelfHealthSignalName.MIXED_MODEL_DISAGREEMENT_RATE] = mixed_model_health_source
    if event_lag_source is not None:
        signals[SelfHealthSignalName.EVENT_LAG] = event_lag_source
    if (canary_result_source is None) != (canary_state_source is None):
        raise ValueError("scheduled canary result and state must share one composed observation")
    if canary_result_source is not None:
        signals[SelfHealthSignalName.CANARY_RESULT] = canary_result_source
    if canary_state_source is not None:
        fields[OperationalStateFieldName.CANARY] = canary_state_source
    signal = SelfHealthSignalName.READINESS_PROBE
    signals[signal] = RuntimeProbeSelfHealthExporter(
        signal, catalog.policies[signal].metric, "runtime:guarded-readiness", readiness
    )
    if liveness is not None:
        signal = SelfHealthSignalName.LIVENESS_PROBE
        signals[signal] = RuntimeProbeSelfHealthExporter(
            signal, catalog.policies[signal].metric, "runtime:health-listener", lambda _: liveness()
        )
    kill_switch = KillSwitchSelfHealthSource(store)
    signals[SelfHealthSignalName.KILL_SWITCH_STATE] = KillSwitchSelfHealthExporter(
        catalog.policies[SelfHealthSignalName.KILL_SWITCH_STATE].metric, kill_switch
    )
    fields[OperationalStateFieldName.KILL_SWITCH] = KillSwitchStateExporter(kill_switch)
    fields[OperationalStateFieldName.VERSION] = InstalledCoreVersionExporter()
    if runtime_policy is not None:
        fields[OperationalStateFieldName.CONFIGURATION] = RuntimeConfigurationExporter(
            canonical_digest(dict(runtime_policy))
        )
    return SelfHealthExporterRegistry(
        catalog=catalog, signal_exporters=signals, state_exporters=fields
    )


def _field(
    name: OperationalStateFieldName,
    source: str,
    maximum_age_seconds: int,
    value_digest: str,
    now: datetime,
) -> OperationalStateFieldV1:
    return OperationalStateFieldV1(
        name=name,
        status=OperationalStateFieldStatus.AVAILABLE,
        value_digest=value_digest,
        source=source,
        observed_at=now,
        maximum_age_seconds=maximum_age_seconds,
        fresh=True,
        reason="current",
    )
