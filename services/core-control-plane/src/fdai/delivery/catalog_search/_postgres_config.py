"""Configuration contract for the PostgreSQL catalog-search adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

EMBEDDING_DIM: Final[int] = 384


@dataclass(frozen=True, slots=True)
class PostgresCatalogSemanticIndexConfig:
    """Bounded connection, vector, and batch settings for catalog search."""

    dsn: str
    statement_timeout_ms: int = 30_000
    connect_timeout_s: int = 10
    ivfflat_probes: int = 10
    write_batch_size: int = 500
    embedding_batch_size: int = 16
    embedding_dimension: int = EMBEDDING_DIM

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresCatalogSemanticIndexConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("database timeouts MUST be >= 1")
        if self.ivfflat_probes < 1:
            raise ValueError("ivfflat_probes MUST be >= 1")
        if not 1 <= self.write_batch_size <= 10_000:
            raise ValueError("write_batch_size MUST be in [1, 10000]")
        if not 1 <= self.embedding_batch_size <= 128:
            raise ValueError("embedding_batch_size MUST be in [1, 128]")
        if self.embedding_dimension != EMBEDDING_DIM:
            raise ValueError(f"embedding_dimension MUST be {EMBEDDING_DIM}")
