"""Runtime composition and refresh lifecycle for startup readiness."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fdai.core.quality_gate.gate import CrossCheckModel
from fdai.core.readiness import (
    AuthorityCeiling,
    EvidenceRequirement,
    ProbeCriticality,
    ReadinessDecision,
    StartupPhase,
    StartupProbeResult,
    StartupProbeSpec,
    StartupReadinessReport,
)
from fdai.core.readiness.coordinator import StartupProbeBudget, StartupReadinessCoordinator
from fdai.delivery.startup_probe import (
    AuditStartupProbe,
    CrossCheckModelStartupProbe,
    EmbeddingModel,
    EmbeddingStartupProbe,
    EnvironmentInjectionStartupProbe,
    EventBusRoundTripStartupProbe,
    KillSwitchStartupProbe,
    StateStoreStartupProbe,
    StaticStartupProbe,
    WorkloadIdentityStartupProbe,
)
from fdai.shared.contracts.validation import EventValidator
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.startup_probe import StartupProbe
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity
from fdai.shared.resilience.kill_switch import StateStoreKillSwitch

_IDENTITY_AUDIENCE = "https://management.azure.com/.default"
_PROBE_TOPIC_DEFAULT = "runtime.startup.probe"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class RuntimeReadinessState:
    """Hold the current report and open processing only while evidence is fresh."""

    report: StartupReadinessReport | None = None
    _ready_event: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    _blocked_event: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.is_ready():
            self._ready_event.set()
        else:
            self._blocked_event.set()

    def update(self, report: StartupReadinessReport) -> None:
        self.report = report
        if self.is_ready():
            self._ready_event.set()
            self._blocked_event.clear()
        else:
            self._ready_event.clear()
            self._blocked_event.set()

    def is_ready(self, *, now: datetime | None = None) -> bool:
        current = self.report
        checked_at = now or _utc_now()
        return bool(
            current is not None
            and current.decision is not ReadinessDecision.BLOCKED
            and all(result.expires_at > checked_at for result in current.results)
            and not current.missing_probe_ids
            and not current.stale_probe_ids
        )

    async def wait_until_ready(self, stop: asyncio.Event) -> bool:
        """Return true on readiness or false when shutdown wins the race."""
        if self.is_ready():
            return True
        ready_task = asyncio.create_task(self._ready_event.wait())
        stop_task = asyncio.create_task(stop.wait())
        done, pending = await asyncio.wait(
            {ready_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        return ready_task in done and self.is_ready()


@dataclass(frozen=True, slots=True)
class StartupReadinessRuntime:
    coordinator: StartupReadinessCoordinator
    state: RuntimeReadinessState
    refresh_interval_seconds: float

    async def evaluate(self) -> StartupReadinessReport:
        report = await self.coordinator.evaluate()
        self.state.update(report)
        return report

    async def refresh_until_stopped(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.refresh_interval_seconds)
            except TimeoutError:
                await self.evaluate()

    async def run_when_ready(
        self,
        stop: asyncio.Event,
        operation: Callable[[], Awaitable[None]],
    ) -> None:
        """Run while ready, cancel on a blocker, and restart after recovery."""
        while not stop.is_set():
            if not await self.state.wait_until_ready(stop):
                return

            async def invoke() -> None:
                await operation()

            operation_task: asyncio.Task[None] = asyncio.create_task(invoke())
            blocked_task = asyncio.create_task(self.state._blocked_event.wait())
            stop_task = asyncio.create_task(stop.wait())
            done, pending = await asyncio.wait(
                {operation_task, blocked_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if operation_task in done:
                await operation_task
                return
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)
            if stop_task in done:
                return


def build_startup_readiness_runtime(
    *,
    state_store: StateStore,
    event_bus: EventBus,
    event_validator: EventValidator,
    identity: WorkloadIdentity,
    embedding_model: EmbeddingModel,
    policy_compile_probe: StartupProbe[StartupProbeResult],
    cross_check_models: Sequence[CrossCheckModel] = (),
    environment: Mapping[str, str],
    registered_specs: Sequence[StartupProbeSpec] = (),
    registered_probes: Sequence[StartupProbe[StartupProbeResult]] = (),
    deployment_ceilings: Mapping[str, AuthorityCeiling] | None = None,
) -> StartupReadinessRuntime:
    """Compose standard required probes plus registered optional destinations."""
    standard_specs = (
        _spec("release.config", "runtime", StartupPhase.STATIC_LOAD),
        _spec("catalog.load", "catalog", StartupPhase.STATIC_LOAD),
        _spec("policy.compile", "policy", StartupPhase.STATIC_LOAD),
        _spec("secret.injection", "secrets", StartupPhase.STATIC_LOAD),
        _spec("identity.token", "identity", StartupPhase.REQUIRED_REACHABILITY),
        _spec("postgres.state", "state", StartupPhase.REQUIRED_REACHABILITY),
        _spec("audit.append", "audit", StartupPhase.ACTIVE_SMOKE, synthetic_scope=True),
        StartupProbeSpec(
            probe_id="kill-switch.read",
            capability="autonomous-action",
            phase=StartupPhase.REQUIRED_REACHABILITY,
            criticality=ProbeCriticality.AUTHORITY_CRITICAL,
            failure_ceiling=AuthorityCeiling.SHADOW,
        ),
        _spec(
            "kafka.round-trip",
            "event-processing",
            StartupPhase.ACTIVE_SMOKE,
            synthetic_scope=True,
        ),
        StartupProbeSpec(
            probe_id="model.embedding",
            capability="t1.embedding",
            phase=StartupPhase.CAPABILITY_WARMUP,
            criticality=ProbeCriticality.AUTHORITY_CRITICAL,
            failure_ceiling=AuthorityCeiling.DETERMINISTIC_FALLBACK,
            evidence_requirement=EvidenceRequirement.MODEL_EMBEDDING,
            estimated_cost_usd=_float_value(environment, "FDAI_STARTUP_EMBEDDING_COST_USD", 0.001),
        ),
    )
    standard_probes: tuple[StartupProbe[StartupProbeResult], ...] = (
        StaticStartupProbe(probe_id="release.config", evidence_key="validated"),
        StaticStartupProbe(probe_id="catalog.load", evidence_key="loaded"),
        policy_compile_probe,
        EnvironmentInjectionStartupProbe(
            probe_id="secret.injection",
            environment=environment,
            required_names=(
                ("FDAI_STATE_STORE_DSN",)
                if environment.get("RUNTIME_ENV", "").strip().casefold() in {"staging", "prod"}
                else ()
            ),
        ),
        WorkloadIdentityStartupProbe(
            probe_id="identity.token",
            identity=identity,
            audience=_IDENTITY_AUDIENCE,
        ),
        StateStoreStartupProbe(probe_id="postgres.state", state_store=state_store),
        AuditStartupProbe(probe_id="audit.append", state_store=state_store),
        KillSwitchStartupProbe(
            probe_id="kill-switch.read",
            refresh=StateStoreKillSwitch(store=state_store).refresh,
        ),
        EventBusRoundTripStartupProbe(
            probe_id="kafka.round-trip",
            event_bus=event_bus,
            topic=environment.get("FDAI_STARTUP_KAFKA_PROBE_TOPIC", "").strip()
            or _PROBE_TOPIC_DEFAULT,
            consumer_settle_seconds=_float_value(
                environment,
                "FDAI_STARTUP_KAFKA_SETTLE_SECONDS",
                0.5,
            ),
        ),
        EmbeddingStartupProbe(probe_id="model.embedding", model=embedding_model),
    )
    model_specs, model_probes = _cross_check_startup_probes(cross_check_models)
    specs = (*standard_specs, *model_specs, *registered_specs)
    probes = (*standard_probes, *model_probes, *registered_probes)
    coordinator = StartupReadinessCoordinator(
        specs=specs,
        probes=probes,
        state_store=state_store,
        event_bus=event_bus,
        event_validator=event_validator,
        deployment_ceilings=deployment_ceilings,
        budget=StartupProbeBudget(
            max_concurrency=_int_value(environment, "FDAI_STARTUP_MAX_CONCURRENCY", 4),
            per_probe_timeout_seconds=_float_value(
                environment,
                "FDAI_STARTUP_PROBE_TIMEOUT_SECONDS",
                10.0,
            ),
            phase_timeout_seconds=_float_value(
                environment,
                "FDAI_STARTUP_PHASE_TIMEOUT_SECONDS",
                30.0,
            ),
            retries=_int_value(environment, "FDAI_STARTUP_PROBE_RETRIES", 1),
            total_cost_limit_usd=_float_value(
                environment,
                "FDAI_STARTUP_COST_LIMIT_USD",
                0.05,
            ),
            model_sample_count=_int_value(
                environment,
                "FDAI_STARTUP_MODEL_SAMPLE_COUNT",
                2,
            ),
        ),
    )
    return StartupReadinessRuntime(
        coordinator=coordinator,
        state=RuntimeReadinessState(),
        refresh_interval_seconds=_float_value(
            environment,
            "FDAI_STARTUP_REFRESH_SECONDS",
            300.0,
        ),
    )


def _spec(
    probe_id: str,
    capability: str,
    phase: StartupPhase,
    *,
    synthetic_scope: bool = False,
) -> StartupProbeSpec:
    return StartupProbeSpec(
        probe_id=probe_id,
        capability=capability,
        phase=phase,
        criticality=ProbeCriticality.PROCESS_CRITICAL,
        failure_ceiling=AuthorityCeiling.DISABLED,
        synthetic_scope=synthetic_scope,
    )


def _cross_check_startup_probes(
    bindings: Sequence[CrossCheckModel],
) -> tuple[tuple[StartupProbeSpec, ...], tuple[CrossCheckModelStartupProbe, ...]]:
    specs: list[StartupProbeSpec] = []
    probes: list[CrossCheckModelStartupProbe] = []
    for binding_index, binding in enumerate(bindings):
        candidates_fn = getattr(binding, "startup_candidates", None)
        candidates = tuple(candidates_fn()) if callable(candidates_fn) else (binding,)
        for candidate_index, candidate in enumerate(candidates):
            probe_id = f"model.cross-check.{binding_index}.{candidate_index}"
            specs.append(
                StartupProbeSpec(
                    probe_id=probe_id,
                    capability=f"t2.cross-check.{binding_index}.{candidate_index}",
                    phase=StartupPhase.CAPABILITY_WARMUP,
                    criticality=ProbeCriticality.AUTHORITY_CRITICAL,
                    failure_ceiling=AuthorityCeiling.HUMAN_APPROVAL,
                    evidence_requirement=EvidenceRequirement.MODEL_STRUCTURED_OUTPUT,
                    estimated_cost_usd=0.001,
                )
            )
            probes.append(CrossCheckModelStartupProbe(probe_id=probe_id, model=candidate))
    return tuple(specs), tuple(probes)


def _int_value(environment: Mapping[str, str], key: str, default: int) -> int:
    raw = environment.get(key, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError as exc:
        raise RuntimeError(f"{key} MUST be an integer") from exc


def _float_value(environment: Mapping[str, str], key: str, default: float) -> float:
    raw = environment.get(key, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError as exc:
        raise RuntimeError(f"{key} MUST be a number") from exc


__all__ = [
    "RuntimeReadinessState",
    "StartupReadinessRuntime",
    "build_startup_readiness_runtime",
]
