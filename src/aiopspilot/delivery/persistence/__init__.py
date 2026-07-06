"""Persistence adapters - CSP-neutral wire-level backends.

These modules realize the persistence-facing Protocols
(:class:`~aiopspilot.shared.providers.state_store.StateStore`,
:class:`~aiopspilot.core.tiers.t1_lightweight.tier.PatternLibrary`)
against real databases (currently PostgreSQL + pgvector). Postgres is
not Azure-specific - the same adapters bind to Cloud SQL, RDS, or a
self-hosted server - so they live here rather than under
``delivery/azure/``.
"""

from __future__ import annotations

from aiopspilot.delivery.persistence.pgvector_pattern_library import (
    PgVectorPatternLibrary,
    PgVectorPatternLibraryConfig,
)
from aiopspilot.delivery.persistence.postgres import (
    PostgresStateStore,
    PostgresStateStoreConfig,
)
from aiopspilot.delivery.persistence.postgres_operator_memory import (
    PostgresOperatorMemoryStore,
    PostgresOperatorMemoryStoreConfig,
)

__all__ = [
    "PgVectorPatternLibrary",
    "PgVectorPatternLibraryConfig",
    "PostgresOperatorMemoryStore",
    "PostgresOperatorMemoryStoreConfig",
    "PostgresStateStore",
    "PostgresStateStoreConfig",
]
