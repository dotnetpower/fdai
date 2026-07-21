"""Environment-selected state, lock, memory, metering, and inventory providers."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fdai.core.executor.lock import ResourceLockManager
from fdai.core.tiers.t1_lightweight.testing import InMemoryPatternLibrary
from fdai.core.tiers.t1_lightweight.tier import PatternLibrary
from fdai.shared.providers.idempotency import IdempotencyStore
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.testing.ontology_instance import InMemoryOntologyInstanceStore
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_LOGGER = logging.getLogger("fdai.startup")
_DURABLE_RUNTIME_ENVS = frozenset({"staging", "prod"})


def _require_durable_backend(*, env_var: str, backend: str) -> None:
    runtime_env = os.environ.get("RUNTIME_ENV", "").strip().lower()
    if runtime_env in _DURABLE_RUNTIME_ENVS:
        raise RuntimeError(
            f"RUNTIME_ENV={runtime_env!r} requires {env_var} for the durable {backend} backend"
        )


def _build_audit_store() -> Any:
    """Select the StateStore backend for this process.

    ``FDAI_STATE_STORE_DSN`` (set by the container's KV secret ref)
    switches to :class:`PostgresStateStore`; without it the in-memory
    fake is used. The ``StateStore`` Protocol is the contract, so core
    code neither knows nor cares which backend is active.
    """
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if dsn:
        from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

        _LOGGER.info("state_store_backend", extra={"backend": "postgres"})
        return PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    _require_durable_backend(env_var="FDAI_STATE_STORE_DSN", backend="state store")
    _LOGGER.info("state_store_backend", extra={"backend": "in-memory"})
    return InMemoryStateStore()


def _build_process_store() -> Any:
    """Select the durable Process snapshot and transition-journal backend."""
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if dsn:
        from fdai.delivery.persistence import (
            PostgresProcessRuntimeStore,
            PostgresProcessRuntimeStoreConfig,
        )

        _LOGGER.info("process_runtime_backend", extra={"backend": "postgres"})
        return PostgresProcessRuntimeStore(config=PostgresProcessRuntimeStoreConfig(dsn=dsn))
    _require_durable_backend(env_var="FDAI_STATE_STORE_DSN", backend="process runtime")
    _LOGGER.info("process_runtime_backend", extra={"backend": "in-memory"})
    return InMemoryProcessRuntimeStore()


def _build_ontology_instance_store(
    *,
    object_types: tuple[Any, ...],
    link_types: tuple[Any, ...],
) -> Any:
    """Select the runtime ontology instance graph backend."""
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if dsn:
        from fdai.delivery.persistence import (
            PostgresOntologyInstanceStore,
            PostgresOntologyInstanceStoreConfig,
        )

        _LOGGER.info("ontology_instance_backend", extra={"backend": "postgres"})
        return PostgresOntologyInstanceStore(
            config=PostgresOntologyInstanceStoreConfig(dsn=dsn),
            object_types=object_types,
            link_types=link_types,
        )
    _require_durable_backend(env_var="FDAI_STATE_STORE_DSN", backend="ontology instance store")
    _LOGGER.info("ontology_instance_backend", extra={"backend": "in-memory"})
    return InMemoryOntologyInstanceStore(
        object_types=object_types,
        link_types=link_types,
    )


def _build_resource_lock() -> ResourceLock:
    """Select the per-resource lock backend for this process.

    ``FDAI_RESOURCE_LOCK_DSN`` (falling back to ``FDAI_STATE_STORE_DSN``)
    switches to the distributed :class:`PostgresAdvisoryResourceLock` so
    per-resource ordering holds across replicas; without a DSN the
    in-process :class:`ResourceLockManager` is used (correct only for a
    single replica). The ``ResourceLock`` Protocol is the contract, so
    the executor neither knows nor cares which backend is active.
    """
    dsn = (
        os.environ.get("FDAI_RESOURCE_LOCK_DSN", "").strip()
        or os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    )
    if not dsn:
        _require_durable_backend(
            env_var="FDAI_RESOURCE_LOCK_DSN or FDAI_STATE_STORE_DSN",
            backend="resource lock",
        )
        _LOGGER.info("resource_lock_backend", extra={"backend": "in-memory"})
        return ResourceLockManager()

    from fdai.delivery.persistence import (
        PostgresAdvisoryResourceLock,
        PostgresAdvisoryResourceLockConfig,
    )

    timeout_raw = os.environ.get("FDAI_RESOURCE_LOCK_TIMEOUT_MS", "").strip()
    try:
        timeout_ms = int(timeout_raw) if timeout_raw else 30_000
    except ValueError as exc:
        raise RuntimeError(
            f"FDAI_RESOURCE_LOCK_TIMEOUT_MS={timeout_raw!r} is not an integer"
        ) from exc
    if timeout_ms < 0:
        raise RuntimeError(f"FDAI_RESOURCE_LOCK_TIMEOUT_MS MUST be >= 0; got {timeout_ms}")

    _LOGGER.info("resource_lock_backend", extra={"backend": "postgres-advisory"})
    return PostgresAdvisoryResourceLock(
        config=PostgresAdvisoryResourceLockConfig(dsn=dsn, lock_timeout_ms=timeout_ms)
    )


def _build_operator_memory_store() -> Any:
    """Select the OperatorMemoryStore backend for this process.

    Mirrors :func:`_build_audit_store`. ``FDAI_OPERATOR_MEMORY_DSN``
    (set by the container's KV secret ref) switches to
    :class:`PostgresOperatorMemoryStore`; without it the deterministic
    in-memory fake is used. The ``OperatorMemoryStore`` Protocol is the
    contract, so :class:`DefaultPromptComposer` neither knows nor cares
    which backend is active.

    Upstream ships with the in-memory backend so the composer is fully
    wired end-to-end even without a database - a fork gets the
    operator-memory layer working the moment it seeds an entry, and
    only needs to set the DSN when it wants durability across
    restarts.
    """

    from fdai.core.operator_memory import InMemoryOperatorMemoryStore

    dsn = os.environ.get("FDAI_OPERATOR_MEMORY_DSN", "").strip()
    if dsn:
        from fdai.delivery.persistence import (
            PostgresOperatorMemoryStore,
            PostgresOperatorMemoryStoreConfig,
        )

        _LOGGER.info("operator_memory_store_backend", extra={"backend": "postgres"})
        return PostgresOperatorMemoryStore(config=PostgresOperatorMemoryStoreConfig(dsn=dsn))
    _require_durable_backend(env_var="FDAI_OPERATOR_MEMORY_DSN", backend="operator memory store")
    _LOGGER.info("operator_memory_store_backend", extra={"backend": "in-memory"})
    return InMemoryOperatorMemoryStore()


def _build_metering_store() -> Any:
    """Select the durable metering sink used by Azure LLM adapters."""
    dsn = (
        os.environ.get("FDAI_METERING_DSN", "").strip()
        or os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    )
    if not dsn:
        _require_durable_backend(
            env_var="FDAI_METERING_DSN or FDAI_STATE_STORE_DSN",
            backend="metering store",
        )
        from fdai.core.metering import InMemoryMeteringSink

        _LOGGER.info("metering_store_backend", extra={"backend": "in-memory"})
        return InMemoryMeteringSink()

    from fdai.delivery.persistence import PostgresMeteringStore, PostgresMeteringStoreConfig

    _LOGGER.info("metering_store_backend", extra={"backend": "postgres"})
    return PostgresMeteringStore(config=PostgresMeteringStoreConfig(dsn=dsn))


def _build_model_health_sink() -> Any | None:
    """Select append-only routing health telemetry when PostgreSQL is configured."""
    dsn = (
        os.environ.get("FDAI_MODEL_HEALTH_DSN", "").strip()
        or os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    )
    if not dsn:
        return None
    from fdai.delivery.persistence import (
        PostgresModelHealthTransitionSink,
        PostgresModelHealthTransitionSinkConfig,
    )

    return PostgresModelHealthTransitionSink(
        config=PostgresModelHealthTransitionSinkConfig(dsn=dsn)
    )


def _build_pattern_library() -> PatternLibrary:
    """Select the :class:`PatternLibrary` backend for this process.

    ``FDAI_T1_PATTERN_LIBRARY_DSN`` (typically the same Postgres
    the state store points at, but broken out so a fork can move the
    T1 store to a dedicated instance) switches to
    :class:`PgVectorPatternLibrary`. Without it the in-memory fake is
    used - the ``PatternLibrary`` Protocol is the contract, so ``core/``
    neither knows nor cares which backend is active.

    Optional tuning envs (fail-fast on unparseable values):

    - ``FDAI_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS`` - default 15000.
    - ``FDAI_T1_PATTERN_LIBRARY_IVFFLAT_PROBES`` - default 10.

    The production control loop binds this library to the configured
    embedding model through :class:`T1Tier`.
    """
    dsn = os.environ.get("FDAI_T1_PATTERN_LIBRARY_DSN", "").strip()
    if not dsn:
        _require_durable_backend(
            env_var="FDAI_T1_PATTERN_LIBRARY_DSN", backend="T1 pattern library"
        )
        _LOGGER.info("pattern_library_backend", extra={"backend": "in-memory"})
        return InMemoryPatternLibrary()

    from fdai.delivery.persistence import (
        PgVectorPatternLibrary,
        PgVectorPatternLibraryConfig,
    )

    timeout_raw = os.environ.get("FDAI_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS", "").strip()
    try:
        timeout_ms = int(timeout_raw) if timeout_raw else 15_000
    except ValueError as exc:
        raise RuntimeError(
            f"FDAI_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS={timeout_raw!r} is not an integer"
        ) from exc
    if timeout_ms < 1:
        raise RuntimeError(
            f"FDAI_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS MUST be >= 1; got {timeout_ms}"
        )

    probes_raw = os.environ.get("FDAI_T1_PATTERN_LIBRARY_IVFFLAT_PROBES", "").strip()
    try:
        probes = int(probes_raw) if probes_raw else 10
    except ValueError as exc:
        raise RuntimeError(
            f"FDAI_T1_PATTERN_LIBRARY_IVFFLAT_PROBES={probes_raw!r} is not an integer"
        ) from exc
    if probes < 1:
        raise RuntimeError(f"FDAI_T1_PATTERN_LIBRARY_IVFFLAT_PROBES MUST be >= 1; got {probes}")

    _LOGGER.info("pattern_library_backend", extra={"backend": "pgvector"})
    return PgVectorPatternLibrary(
        config=PgVectorPatternLibraryConfig(
            dsn=dsn,
            statement_timeout_ms=timeout_ms,
            ivfflat_probes=probes,
        )
    )


def _build_idempotency_store() -> IdempotencyStore | None:
    """Select the durable idempotency backend for this process.

    ``FDAI_IDEMPOTENCY_DSN`` (falling back to ``FDAI_STATE_STORE_DSN``)
    switches on the durable :class:`PostgresIdempotencyStore` so a
    post-restart / cross-replica re-delivery of a *mutating* action is
    returned from the store instead of re-executed. Without a DSN the
    executor uses its in-process L1 cache only (existing single-replica
    behavior); ``None`` signals that.
    """
    dsn = (
        os.environ.get("FDAI_IDEMPOTENCY_DSN", "").strip()
        or os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    )
    if not dsn:
        _require_durable_backend(
            env_var="FDAI_IDEMPOTENCY_DSN or FDAI_STATE_STORE_DSN",
            backend="idempotency store",
        )
        _LOGGER.info("idempotency_backend", extra={"backend": "in-process-l1-only"})
        return None

    from fdai.delivery.persistence import (
        PostgresIdempotencyStore,
        PostgresIdempotencyStoreConfig,
    )

    _LOGGER.info("idempotency_backend", extra={"backend": "postgres"})
    return PostgresIdempotencyStore(config=PostgresIdempotencyStoreConfig(dsn=dsn))


def _build_inventory_age_provider() -> Any:
    dsn = (
        os.environ.get("FDAI_INVENTORY_DSN", "").strip()
        or os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    )
    if not dsn:
        _require_durable_backend(
            env_var="FDAI_INVENTORY_DSN or FDAI_STATE_STORE_DSN",
            backend="inventory age provider",
        )
        return None
    from fdai.delivery.persistence.postgres_inventory_snapshot import (
        PostgresInventoryAgeProvider,
        PostgresInventorySnapshotStoreConfig,
    )

    return PostgresInventoryAgeProvider(config=PostgresInventorySnapshotStoreConfig(dsn=dsn))


def _build_inventory_context_provider() -> Any:
    dsn = (
        os.environ.get("FDAI_INVENTORY_DSN", "").strip()
        or os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    )
    if not dsn:
        _require_durable_backend(
            env_var="FDAI_INVENTORY_DSN or FDAI_STATE_STORE_DSN",
            backend="inventory context provider",
        )
        return None
    from fdai.delivery.persistence.postgres_inventory_snapshot import (
        PostgresInventoryContextProvider,
        PostgresInventorySnapshotStoreConfig,
    )

    return PostgresInventoryContextProvider(config=PostgresInventorySnapshotStoreConfig(dsn=dsn))


def _build_inventory_delta_projector() -> Any:
    dsn = (
        os.environ.get("FDAI_INVENTORY_DSN", "").strip()
        or os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    )
    if not dsn:
        _require_durable_backend(
            env_var="FDAI_INVENTORY_DSN or FDAI_STATE_STORE_DSN",
            backend="inventory delta projector",
        )
        return None
    from fdai.delivery.persistence.postgres_inventory_delta import (
        PostgresInventoryDeltaProjector,
    )
    from fdai.delivery.persistence.postgres_inventory_snapshot import (
        PostgresInventorySnapshotStoreConfig,
    )

    projector = PostgresInventoryDeltaProjector(
        config=PostgresInventorySnapshotStoreConfig(dsn=dsn)
    )
    if (
        os.environ.get("RUNTIME_ENV", "").strip().lower() == "dev"
        and os.environ.get("FDAI_RUNTIME_LOCAL_AZURE_CLI", "").strip() == "1"
    ):
        subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
        if not subscription_id:
            return projector
        from fdai.delivery.inventory_cache_invalidation import (
            InvalidatingInventoryDeltaProjector,
        )
        from fdai.delivery.read_api.dev.azure_inventory_graph import (
            inventory_cache_path,
            inventory_invalidation_path,
        )

        cache_path, _ = inventory_cache_path(
            repo_root=Path(__file__).resolve().parents[3],
            subscription_id=subscription_id,
            azure_config_dir=os.environ.get("FDAI_LOCAL_AZURE_CONFIG_DIR", "").strip() or None,
        )

        return InvalidatingInventoryDeltaProjector(
            inner=projector,
            marker_path=inventory_invalidation_path(cache_path),
        )
    return projector
