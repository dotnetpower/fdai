"""Persistence adapters - CSP-neutral wire-level backends.

These modules realize the persistence-facing Protocols
(:class:`~fdai.shared.providers.state_store.StateStore`,
:class:`~fdai.core.tiers.t1_lightweight.tier.PatternLibrary`)
against real databases (currently PostgreSQL + pgvector). Postgres is
not Azure-specific - the same adapters bind to Cloud SQL, RDS, or a
self-hosted server - so they live here rather than under
``delivery/azure/``.
"""

from __future__ import annotations

from fdai.delivery.persistence.pgvector_pattern_library import (
    PgVectorPatternLibrary,
    PgVectorPatternLibraryConfig,
)
from fdai.delivery.persistence.postgres import (
    PostgresStateStore,
    PostgresStateStoreConfig,
)
from fdai.delivery.persistence.postgres_idempotency import (
    PostgresIdempotencyStore,
    PostgresIdempotencyStoreConfig,
)
from fdai.delivery.persistence.postgres_operator_memory import (
    PostgresOperatorMemoryStore,
    PostgresOperatorMemoryStoreConfig,
)
from fdai.delivery.persistence.postgres_outbox import (
    PostgresOutboxStore,
    PostgresOutboxStoreConfig,
)
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)

__all__ = [
    "PgVectorPatternLibrary",
    "PgVectorPatternLibraryConfig",
    "PostgresAdvisoryResourceLock",
    "PostgresAdvisoryResourceLockConfig",
    "PostgresIdempotencyStore",
    "PostgresIdempotencyStoreConfig",
    "PostgresOperatorMemoryStore",
    "PostgresOperatorMemoryStoreConfig",
    "PostgresOutboxStore",
    "PostgresOutboxStoreConfig",
    "PostgresStateStore",
    "PostgresStateStoreConfig",
]
