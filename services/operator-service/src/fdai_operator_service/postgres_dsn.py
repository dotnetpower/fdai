"""PostgreSQL DSN normalization for direct Psycopg connections."""

from __future__ import annotations


def normalize_psycopg_dsn(value: str) -> str:
    """Remove the SQLAlchemy driver marker before direct Psycopg use."""

    prefix = "postgresql+psycopg://"
    normalized = f"postgresql://{value[len(prefix) :]}" if value.startswith(prefix) else value
    if normalized in {"postgres://", "postgresql://"}:
        raise ValueError("PostgreSQL DSN MUST include a connection target")
    return normalized


__all__ = ["normalize_psycopg_dsn"]
