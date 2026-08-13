"""Configuration, health, and shutdown helpers for runtime bootstrap."""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import signal
from collections.abc import Callable, Coroutine, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, Any

from fdai_core_service.semantic_turn_consumer import (
    SemanticTurnConsumerBinding,
    semantic_turn_binding_from_config,
)

from fdai.agents import Saga, SemanticRouterConfig, StateStoreAuditChainAdapter
from fdai.agents.vidar import RollbackExecutor
from fdai.core.control_loop import ControlLoop
from fdai.core.executor import MutationDependencyReadiness
from fdai.core.readiness import (
    AuthorityCeiling,
    ProbeCriticality,
    ProbeStatus,
    StartupPhase,
    StartupProbeResult,
    StartupProbeSpec,
)
from fdai.core.rule_semantic_generation import (
    RuleGenerationOutboxPublisher,
    RuleGenerationPublishRetryableError,
)
from fdai.core.tiers.t1_lightweight.tier import EmbeddingModel
from fdai.delivery.catalog_search.postgres import (
    PostgresCatalogSemanticIndex,
    PostgresCatalogSemanticIndexConfig,
)
from fdai.delivery.reconciliation_runtime import EffectReconciliationWorker
from fdai.rule_catalog.schema.catalog_search import (
    catalog_search_schema_digest,
    rule_reference_catalog_digest,
)
from fdai.runtime.health import RuntimeHealthServer
from fdai.runtime.readiness import StartupReadinessRuntime
from fdai.shared.contracts.models import OntologyRelease, Rule
from fdai.shared.providers.catalog_search import (
    CatalogGenerationMetadata,
    CatalogSemanticIndex,
)
from fdai.shared.providers.startup_probe import StartupProbeRequest
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.startup")
_SEMANTIC_TURN_READINESS_PROBE_ID = "semantic-turn.runtime"
_CATALOG_SEMANTIC_READINESS_PROBE_ID = "catalog-semantic.runtime"


@dataclass(frozen=True, slots=True)
class CatalogSemanticRuntimeBinding:
    """Exact active-generation binding for candidate-only Rule retrieval."""

    index: CatalogSemanticIndex | None
    catalog_digest: str | None
    generation: CatalogGenerationMetadata | None
    unavailable_reason: str | None

    @property
    def available(self) -> bool:
        return (
            self.index is not None
            and self.catalog_digest is not None
            and self.generation is not None
            and self.unavailable_reason is None
        )


class CatalogSemanticReadinessProbe:
    """Project optional Rule semantic retrieval availability into readiness."""

    probe_id = _CATALOG_SEMANTIC_READINESS_PROBE_ID

    def __init__(self, binding: CatalogSemanticRuntimeBinding) -> None:
        self._binding = binding

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        observed_at = datetime.now(UTC)
        expires_at = max(request.deadline, observed_at + timedelta(seconds=1))
        return StartupProbeResult(
            probe_id=self.probe_id,
            status=ProbeStatus.PASSED if self._binding.available else ProbeStatus.FAILED,
            observed_at=observed_at,
            expires_at=expires_at,
            latency_ms=0,
            failure_class=(
                None
                if self._binding.available
                else self._binding.unavailable_reason or "catalog_semantic_generation_unavailable"
            ),
            evidence={"runtime_bound": self._binding.available},
        )


async def build_catalog_semantic_runtime_binding(
    *,
    config: Mapping[str, str],
    embedder: EmbeddingModel,
    rules: Sequence[Rule],
    ontology_release: OntologyRelease | None,
) -> CatalogSemanticRuntimeBinding:
    """Bind only an active generation matching every current runtime identity."""

    dsn = config.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        return _catalog_semantic_unavailable("catalog_semantic_state_store_unavailable")
    if ontology_release is None:
        return _catalog_semantic_unavailable("catalog_semantic_ontology_unavailable")

    index = PostgresCatalogSemanticIndex(
        config=PostgresCatalogSemanticIndexConfig(
            dsn=dsn,
            embedding_dimension=embedder.dim,
        ),
        embedder=embedder,
    )
    try:
        generation = await index.active_generation("active")
    except Exception:  # noqa: BLE001 - optional provider details stay outside readiness
        return _catalog_semantic_unavailable("catalog_semantic_generation_inaccessible")
    if generation is None:
        return _catalog_semantic_unavailable("catalog_semantic_generation_unavailable")

    catalog_digest = rule_reference_catalog_digest(rules)
    if (
        generation.corpus != "active"
        or generation.state != "active"
        or generation.catalog_digest != catalog_digest
        or generation.semantic_schema_digest != catalog_search_schema_digest()
        or generation.ontology_release_digest != ontology_release.digest
        or generation.embedding_dimension != embedder.dim
    ):
        return _catalog_semantic_unavailable("catalog_semantic_generation_stale")
    return CatalogSemanticRuntimeBinding(
        index=index,
        catalog_digest=catalog_digest,
        generation=generation,
        unavailable_reason=None,
    )


def catalog_semantic_readiness_registration(
    binding: CatalogSemanticRuntimeBinding,
) -> tuple[tuple[StartupProbeSpec, ...], tuple[CatalogSemanticReadinessProbe, ...]]:
    """Register Rule semantic retrieval as an optional degraded capability."""

    return (
        (
            StartupProbeSpec(
                probe_id=_CATALOG_SEMANTIC_READINESS_PROBE_ID,
                capability="catalog-semantic-retrieval",
                phase=StartupPhase.CAPABILITY_WARMUP,
                criticality=ProbeCriticality.OPTIONAL,
                failure_ceiling=AuthorityCeiling.DISABLED,
            ),
        ),
        (CatalogSemanticReadinessProbe(binding),),
    )


def _catalog_semantic_unavailable(reason: str) -> CatalogSemanticRuntimeBinding:
    return CatalogSemanticRuntimeBinding(
        index=None,
        catalog_digest=None,
        generation=None,
        unavailable_reason=reason,
    )


class SemanticTurnReadinessProbe:
    """Project the configured semantic runtime binding into startup readiness."""

    probe_id = _SEMANTIC_TURN_READINESS_PROBE_ID

    def __init__(self, binding: SemanticTurnConsumerBinding) -> None:
        self._binding = binding

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        observed_at = datetime.now(UTC)
        expires_at = max(request.deadline, observed_at + timedelta(seconds=1))
        return StartupProbeResult(
            probe_id=self.probe_id,
            status=ProbeStatus.PASSED if self._binding.available else ProbeStatus.FAILED,
            observed_at=observed_at,
            expires_at=expires_at,
            latency_ms=0,
            failure_class=(
                None
                if self._binding.available
                else self._binding.unavailable_reason or "semantic_runtime_unavailable"
            ),
            evidence={"runtime_bound": self._binding.available},
        )


def build_semantic_turn_binding(
    *,
    state_store: StateStore,
    config: Mapping[str, str],
    runtime: Any = None,
    unavailable_reason: str | None = None,
) -> SemanticTurnConsumerBinding | None:
    """Bind configured transport and its explicit runtime availability state."""

    return semantic_turn_binding_from_config(
        state_store=state_store,
        runtime=runtime,
        config=config,
        unavailable_reason=unavailable_reason,
    )


def semantic_turn_readiness_registration(
    binding: SemanticTurnConsumerBinding | None,
) -> tuple[tuple[StartupProbeSpec, ...], tuple[SemanticTurnReadinessProbe, ...]]:
    if binding is None:
        return (), ()
    return (
        (
            StartupProbeSpec(
                probe_id=_SEMANTIC_TURN_READINESS_PROBE_ID,
                capability="semantic-query",
                phase=StartupPhase.CAPABILITY_WARMUP,
                criticality=ProbeCriticality.OPTIONAL,
                failure_ceiling=AuthorityCeiling.DISABLED,
            ),
        ),
        (SemanticTurnReadinessProbe(binding),),
    )


def semantic_router_config_from_env() -> SemanticRouterConfig:
    def setting(name: str, default: float) -> float:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name} MUST be a float") from exc

    return SemanticRouterConfig(
        cosine_threshold=setting("FDAI_AGENT_SEMANTIC_COSINE_THRESHOLD", 0.65),
        margin_threshold=setting("FDAI_AGENT_SEMANTIC_MARGIN_THRESHOLD", 0.08),
    )


def build_runtime_saga(state_store: StateStore) -> Saga:
    return Saga(audit_chain=StateStoreAuditChainAdapter(store=state_store))


def build_mutation_dependency_readiness(
    *,
    saga: Saga,
    rollback_executors: Mapping[str, RollbackExecutor] | None,
) -> MutationDependencyReadiness:
    """Project existing Saga and Vidar bindings into mutation readiness evidence."""
    return MutationDependencyReadiness(
        saga_audit_durable=saga.durable_audit,
        vidar_recovery_contracts=frozenset(rollback_executors or ()),
    )


build_thor_safety_dependency_readiness = build_mutation_dependency_readiness


def raise_required_task_failure(done: set[asyncio.Task[Any]]) -> None:
    for task in done:
        if task.cancelled():
            continue
        failure = task.exception()
        if failure is None:
            continue
        _LOGGER.error(
            "required_runtime_task_failed",
            extra={"task": task.get_name()},
            exc_info=failure,
        )
        raise RuntimeError(f"required runtime task failed: {task.get_name()}") from failure


def runtime_positive_integer(values: dict[str, object], key: str) -> int:
    value = values.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RuntimeError(f"effective runtime setting {key} is invalid")
    return value


async def supervise_runtime_tasks(
    required: Sequence[asyncio.Task[Any] | None],
    background: Sequence[asyncio.Task[Any] | None],
) -> None:
    """Wait on the required tasks, then cancel and drain every runtime task.

    Blast-radius isolation: ``background`` tasks (the pantheon overlay) stay
    out of the wait set so their exit cannot terminate the primary pipeline.
    Every task is still cancelled and awaited, so a consumer's ``async for``
    plus ``finally`` drains before the caller tears down the bus and HTTP
    client. A required task that failed re-raises after the drain.
    """

    wait_set = {task for task in required if task is not None}
    done, _pending = await asyncio.wait(wait_set, return_when=asyncio.FIRST_COMPLETED)
    tracked = [task for task in (*required, *background) if task is not None]
    for task in tracked:
        task.cancel()
    await asyncio.gather(*tracked, return_exceptions=True)
    raise_required_task_failure(done)


async def run_effect_reconciliation(
    *,
    worker: EffectReconciliationWorker,
    stop: asyncio.Event,
    drain_limit: int = 100,
    drain_interval_seconds: float = 1.0,
    shutdown_timeout_seconds: float = 5.0,
) -> None:
    """Supervise request subscription and bounded outbox draining until shutdown.

    Each outbox pass publishes at most ``drain_limit`` events, yields to sibling tasks, and then
    waits on the shared stop signal. Shutdown cancels both children and bounds their final drain so
    a broken transport cannot hold process termination indefinitely.
    """
    if not 1 <= drain_limit <= 1000:
        raise ValueError("reconciliation drain limit MUST be in [1, 1000]")
    if drain_interval_seconds <= 0 or shutdown_timeout_seconds <= 0:
        raise ValueError("reconciliation lifecycle timeouts MUST be positive")

    async def drain_outbox() -> None:
        while not stop.is_set():
            await worker.drain_pending(limit=drain_limit)
            await asyncio.sleep(0)
            try:
                async with asyncio.timeout(drain_interval_seconds):
                    await stop.wait()
            except TimeoutError:
                continue

    subscriber = asyncio.create_task(
        worker.run_subscriber(),
        name="effect-reconciliation-subscriber",
    )
    drainer = asyncio.create_task(
        drain_outbox(),
        name="effect-reconciliation-outbox",
    )
    stop_waiter = asyncio.create_task(stop.wait(), name="effect-reconciliation-stop")
    tasks = (subscriber, drainer, stop_waiter)
    try:
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task is stop_waiter:
                continue
            task.result()
            if stop.is_set():
                continue
            raise RuntimeError(f"reconciliation lifecycle task exited: {task.get_name()}")
    finally:
        for task in tasks:
            task.cancel()
        try:
            async with asyncio.timeout(shutdown_timeout_seconds):
                await asyncio.gather(*tasks, return_exceptions=True)
        except TimeoutError:
            _LOGGER.warning("effect_reconciliation_shutdown_timed_out")


async def run_rule_generation_outbox_publisher(
    *,
    publisher: RuleGenerationOutboxPublisher,
    stop: asyncio.Event,
    drain_limit: int = 100,
    drain_interval_seconds: float = 1.0,
) -> None:
    """Publish bounded activation-result batches until shutdown or a fatal failure."""

    if not 1 <= drain_limit <= 1000:
        raise ValueError("Rule generation outbox drain limit MUST be in [1, 1000]")
    if drain_interval_seconds <= 0:
        raise ValueError("Rule generation outbox drain interval MUST be positive")

    while not stop.is_set():
        try:
            await publisher.drain_pending(limit=drain_limit)
        except RuleGenerationPublishRetryableError as exc:
            _LOGGER.warning(
                "rule_generation_outbox_publish_retry_scheduled",
                extra={"error_type": type(exc.__cause__).__name__},
                exc_info=exc,
            )
        await asyncio.sleep(0)
        try:
            async with asyncio.timeout(drain_interval_seconds):
                await stop.wait()
        except TimeoutError:
            continue


def log_rule_generation_outbox_exit(task: asyncio.Task[None]) -> None:
    """Surface fatal or unexpected publisher exits from its isolated task."""

    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _LOGGER.error("rule_generation_outbox_failed", exc_info=exc)
    else:
        _LOGGER.warning("rule_generation_outbox_exited_early")


async def start_health_server(
    *,
    control_loop: ControlLoop | None,
    startup_readiness: StartupReadinessRuntime | None,
) -> RuntimeHealthServer | None:
    raw_port = os.environ.get("FDAI_HEALTH_PORT", "").strip()
    if not raw_port:
        return None
    if control_loop is None:
        raise RuntimeError(
            "FDAI_HEALTH_PORT requires a ready control loop; set FDAI_START_CONSUMER=1"
        )
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise RuntimeError("FDAI_HEALTH_PORT MUST be an integer") from exc
    if startup_readiness is None:
        raise RuntimeError("FDAI_HEALTH_PORT requires startup readiness composition")
    server = RuntimeHealthServer(
        port=port,
        readiness=startup_readiness.state.is_ready,
    )
    await server.start()
    _LOGGER.info("health_server_ready", extra={"port": port})
    return server


def install_shutdown_signals() -> asyncio.Event:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def signal_stop(signame: str) -> None:
        _LOGGER.info("shutdown_signal", extra={"signal": signame})
        stop.set()

    for handled_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(handled_signal, signal_stop, handled_signal.name)
    return stop


@contextmanager
def runtime_process_lock() -> Any:
    raw_path = os.environ.get("FDAI_RUNTIME_LOCK_FILE", "").strip()
    if (
        not raw_path
        and os.environ.get("RUNTIME_ENV", "").strip().lower() == "dev"
        and os.environ.get("FDAI_RUNTIME_LOCAL_AZURE_CLI", "").strip() == "1"
    ):
        raw_path = ".fdai/core-runtime.lock"
    if not raw_path:
        yield
        return
    path = Path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream: IO[str] = path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"FDAI runtime is already active for lock file {path}") from exc
        yield
    finally:
        stream.close()


def run_main(run: Callable[[], Coroutine[Any, Any, int]]) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s :: %(message)s",
        force=True,
    )
    try:
        with runtime_process_lock():
            return asyncio.run(run())
    except KeyboardInterrupt:
        return 0
