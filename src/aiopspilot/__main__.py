"""Process entrypoint — headless control plane bootstrap + event loop.

Loads the composition-root container, finalizes the LLM bindings against
Managed Identity when ``llm.mode == "azure"``, boots the P1 control
loop (``event-ingest → trust-router → T0 → executor → audit``) and
subscribes to the configured Kafka topic on the injected event bus.

Fail-fast contract:

- Missing or invalid env aborts before the event loop starts.
- ``llm.mode='azure'`` requires the Managed Identity endpoint envs; the
  ``ManagedIdentityWorkloadIdentity`` adapter raises when they are
  missing so a container that was miswired never masquerades as ready.
- ShadowExecutor + InMemoryStateStore + RecordingRemediationPrPublisher
  are the initial P1 wiring — every autonomous action is judged and
  audited, but no real PR is opened yet. A follow-up phase replaces
  those seams with the GitHub Checks + Postgres StateStore adapters.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

from .composition import (
    Container,
    LlmBindings,
    bind_azure_llm_bindings,
    default_container_from_env,
)
from .core.control_loop import ControlLoop
from .core.event_ingest import EventIngest
from .core.executor import ShadowExecutor
from .core.executor.action_builder import ActionBuilder
from .core.executor.lock import ResourceLockManager
from .core.executor.renderer import TemplateRenderer
from .core.tiers.t0_deterministic import T0Engine
from .core.tiers.t0_deterministic.index import RuleIndex
from .core.tiers.t0_deterministic.opa_evaluator import (
    MissingOpaBinaryError,
    OpaRegoEvaluator,
)
from .core.trust_router import TrustRouter
from .rule_catalog.schema.action_type import load_action_type_catalog
from .rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from .rule_catalog.schema.rule import load_rule_catalog
from .shared.config.models import LlmMode
from .shared.providers.event_bus import EventBus
from .shared.providers.testing.remediation_pr import RecordingRemediationPrPublisher
from .shared.providers.testing.state_store import InMemoryStateStore
from .shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("aiopspilot.startup")
_LOOP_LOGGER = logging.getLogger("aiopspilot.control_loop")


def _resolve_catalog_root() -> Path:
    """Locate the rule-catalog/ tree across dev + container layouts.

    - Dev / editable install: ``<repo>/rule-catalog/`` next to ``src/``.
    - Docker runtime: ``/app/rule-catalog/`` (see Dockerfile).
    - Explicit override via ``AIOPSPILOT_CATALOG_ROOT`` env.

    A missing tree is a fail-fast error — the control loop can't start
    without at least one rule.
    """
    override = os.environ.get("AIOPSPILOT_CATALOG_ROOT")
    if override:
        candidate = Path(override)
        if candidate.is_dir():
            return candidate
        raise FileNotFoundError(f"AIOPSPILOT_CATALOG_ROOT={override!r} is not a directory")

    # Walk up from this module looking for a rule-catalog/ sibling.
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        cand = parent / "rule-catalog"
        if (cand / "catalog").is_dir():
            return cand

    # Container image default (Dockerfile copies to /app/rule-catalog).
    for absolute in (Path("/app/rule-catalog"), Path.cwd() / "rule-catalog"):
        if (absolute / "catalog").is_dir():
            return absolute

    raise FileNotFoundError("Could not locate the rule-catalog tree. Set AIOPSPILOT_CATALOG_ROOT.")


def _resolve_policies_root(catalog_root: Path) -> Path:
    """Sibling policies/ tree; same override + walk-up as catalog."""
    override = os.environ.get("AIOPSPILOT_POLICIES_ROOT")
    if override:
        candidate = Path(override)
        if candidate.is_dir():
            return candidate
        raise FileNotFoundError(f"AIOPSPILOT_POLICIES_ROOT={override!r} is not a directory")
    sibling = catalog_root.parent / "policies"
    if sibling.is_dir():
        return sibling
    for absolute in (Path("/app/policies"), Path.cwd() / "policies"):
        if absolute.is_dir():
            return absolute
    raise FileNotFoundError("Could not locate the policies/ tree. Set AIOPSPILOT_POLICIES_ROOT.")


def _build_audit_store() -> Any:
    """Select the StateStore backend for this process.

    ``AIOPSPILOT_STATE_STORE_DSN`` (set by the container's KV secret ref)
    switches to :class:`PostgresStateStore`; without it the in-memory
    fake is used. The ``StateStore`` Protocol is the contract, so core
    code neither knows nor cares which backend is active.
    """
    dsn = os.environ.get("AIOPSPILOT_STATE_STORE_DSN")
    if dsn:
        from .delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

        _LOGGER.info("state_store_backend", extra={"backend": "postgres"})
        return PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    _LOGGER.info("state_store_backend", extra={"backend": "in-memory"})
    return InMemoryStateStore()


def _summarize_config(container: Container) -> dict[str, Any]:
    """Return a secret-free view of the loaded config for the startup log."""
    cfg = container.config
    return {
        "env": cfg.runtime.env,
        "autonomy_mode_default": cfg.runtime.autonomy_mode_default.value,
        "azure_region": cfg.azure.region,
        "kafka_bootstrap": cfg.kafka.bootstrap_servers,
        "kafka_topic_events": cfg.kafka.topic_events,
        "postgres_host": cfg.postgres.host,
        "postgres_db": cfg.postgres.database,
        "llm_mode": cfg.llm.mode,
        "llm_capabilities": list(cfg.llm.capabilities),
        "llm_bindings_available": container.llm_bindings is not None,
    }


async def _finalize_llm_bindings(
    container: Container,
    *,
    http_client: httpx.AsyncClient,
    identity: WorkloadIdentity,
) -> Container:
    """When mode=azure, attach the real AOAI adapters. Otherwise no-op."""
    if container.config.llm.mode != LlmMode.AZURE:
        return container
    endpoint = os.environ.get("AIOPSPILOT_LLM_ENDPOINT")
    if not endpoint:
        raise RuntimeError(
            "llm.mode='azure' requires AIOPSPILOT_LLM_ENDPOINT env "
            "(e.g. https://oai-aiopspilot-dev-krc.openai.azure.com)"
        )
    return bind_azure_llm_bindings(
        container,
        identity=identity,
        http_client=http_client,
        endpoint=endpoint,
    )


def _build_control_loop(container: Container) -> ControlLoop:
    """Load rule / action / policy catalogs and wire the P1 control loop."""
    catalog_root = _resolve_catalog_root()
    policies_root = _resolve_policies_root(catalog_root)
    action_types_root = catalog_root / "action-types"
    vocabulary_file = catalog_root / "vocabulary" / "resource-types.yaml"
    remediation_root = catalog_root / "remediation"
    rules_root = catalog_root / "catalog"

    registry = container.schema_registry
    action_types = load_action_type_catalog(action_types_root, schema_registry=registry)
    with vocabulary_file.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    rules = load_rule_catalog(
        rules_root,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=policies_root,
        remediation_root=remediation_root,
    )
    index = RuleIndex.build(rules)

    try:
        evaluator: Any = OpaRegoEvaluator(policies_root=policies_root)
    except MissingOpaBinaryError:
        # opa binary is required for full T0 verdicts; without it, T0
        # abstains on every candidate. Log the fact and continue so the
        # loop still exercises event-ingest + routing paths.
        _LOGGER.warning("opa_binary_missing_fallback_to_abstain")
        evaluator = None

    t0 = T0Engine(index=index, evaluator=evaluator)
    trust_router = TrustRouter(index=index)
    event_ingest = EventIngest(validator=container.event_validator)
    action_types_by_name = {a.name: a for a in action_types}
    action_builder = ActionBuilder(action_types_by_name=action_types_by_name)

    audit_store = _build_audit_store()
    publisher = RecordingRemediationPrPublisher()
    renderer = TemplateRenderer(remediation_root=remediation_root)
    resource_lock = ResourceLockManager()

    executor = ShadowExecutor(
        publisher=publisher,
        audit_store=audit_store,
        renderer=renderer,
        resource_lock=resource_lock,
    )

    return ControlLoop(
        event_ingest=event_ingest,
        trust_router=trust_router,
        t0_engine=t0,
        action_builder=action_builder,
        executor=executor,
        audit_store=audit_store,
        rules_by_id={r.id: r for r in rules},
    )


async def _consume(
    *,
    bus: EventBus,
    topic: str,
    group_id: str,
    control_loop: ControlLoop,
    stop: asyncio.Event,
) -> None:
    """Feed every Kafka envelope through the P1 control loop.

    :meth:`ControlLoop.process` is idempotent on ``idempotency_key`` and
    never raises for business errors, so a bad event still writes an
    audit entry and the consumer keeps committing offsets to avoid
    poison-message deadlocks.
    """
    async for envelope in bus.subscribe(topic, group_id):
        if stop.is_set():
            return
        _LOOP_LOGGER.info(
            "event_received",
            extra={"topic": envelope.topic, "offset": envelope.offset, "key": envelope.key},
        )
        try:
            result = await control_loop.process(envelope.payload)
        except Exception:  # noqa: BLE001 — fail-close: log-and-continue
            _LOOP_LOGGER.exception(
                "control_loop_unhandled_error",
                extra={"key": envelope.key, "offset": envelope.offset},
            )
            continue
        _LOOP_LOGGER.info(
            "event_processed",
            extra={
                "outcome": result.outcome.value,
                "tier": result.tier,
                "decision": result.decision,
                "resource_type": result.resource_type,
                "citing_rule_ids": list(result.citing_rule_ids),
            },
        )


async def _run() -> int:
    container = default_container_from_env()
    summary = _summarize_config(container)
    _LOGGER.info("startup_ok", extra={"config": summary})

    http_client: httpx.AsyncClient | None = None
    identity: WorkloadIdentity | None = None
    bus: EventBus | None = None

    try:
        if container.config.llm.mode == LlmMode.AZURE:
            from .delivery.azure.workload_identity import (
                ManagedIdentityWorkloadIdentity,
            )

            http_client = httpx.AsyncClient()
            identity = ManagedIdentityWorkloadIdentity(http_client=http_client)
            container = await _finalize_llm_bindings(
                container, http_client=http_client, identity=identity
            )
            bindings: LlmBindings = container.require_llm_bindings()
            _LOGGER.info(
                "azure_llm_bindings_attached",
                extra={"cross_check_models": len(bindings.cross_check_models)},
            )

        start_consumer = os.environ.get("AIOPSPILOT_START_CONSUMER", "").lower() in (
            "1",
            "true",
        )
        control_loop: ControlLoop | None = None

        if start_consumer:
            from .delivery.azure.event_bus import (
                EventHubsKafkaBus,
                EventHubsKafkaBusConfig,
            )

            if identity is None:
                from .delivery.azure.workload_identity import (
                    ManagedIdentityWorkloadIdentity,
                )

                if http_client is None:
                    http_client = httpx.AsyncClient()
                identity = ManagedIdentityWorkloadIdentity(http_client=http_client)

            bus = EventHubsKafkaBus(
                identity=identity,
                config=EventHubsKafkaBusConfig(
                    bootstrap_servers=container.config.kafka.bootstrap_servers,
                    dlq_suffix=container.config.kafka.topic_dlq_suffix,
                ),
            )
            control_loop = _build_control_loop(container)
            _LOGGER.info(
                "control_loop_ready",
                extra={
                    "topic": container.config.kafka.topic_events,
                    "group_id": "aiopspilot-core",
                },
            )

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _signal_stop(signame: str) -> None:
            _LOGGER.info("shutdown_signal", extra={"signal": signame})
            stop.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _signal_stop, sig.name)

        if bus is not None and control_loop is not None:
            consumer_task = asyncio.create_task(
                _consume(
                    bus=bus,
                    topic=container.config.kafka.topic_events,
                    group_id="aiopspilot-core",
                    control_loop=control_loop,
                    stop=stop,
                )
            )
            wait_task = asyncio.create_task(stop.wait())
            done, _pending = await asyncio.wait(
                {consumer_task, wait_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            consumer_task.cancel()
            wait_task.cancel()
            for task in done:
                exc = task.exception()
                if exc is not None:
                    _LOGGER.error("consumer_task_failed", exc_info=exc)
        else:
            await stop.wait()

        _LOGGER.info("shutdown_complete")
        return 0
    finally:
        if bus is not None:
            close = getattr(bus, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    _LOGGER.warning("bus_close_failed", exc_info=True)
        if http_client is not None:
            try:
                await http_client.aclose()
            except Exception:  # noqa: BLE001
                _LOGGER.warning("http_client_close_failed", exc_info=True)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s :: %(message)s",
    )
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":  # pragma: no cover — process entrypoint
    sys.exit(main())
