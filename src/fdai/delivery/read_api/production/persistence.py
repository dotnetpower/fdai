"""Shared production persistence configuration and base adapters."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.delivery.persistence import PostgresStateStore
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.delivery.read_api.postgres_read_model import PostgresConsoleReadModel


@dataclass(frozen=True, slots=True)
class ProductionPersistence:
    """Database settings shared by production read API adapters."""

    read_model: PostgresConsoleReadModel
    state_store_config: PostgresStateStoreConfig
    state_store: PostgresStateStore


def build_production_persistence(
    read_model: PostgresConsoleReadModel,
) -> ProductionPersistence:
    """Derive the shared state-store adapter from the read-model settings."""
    config = PostgresStateStoreConfig(
        dsn=read_model._config.dsn,
        statement_timeout_ms=read_model._config.statement_timeout_ms,
        connect_timeout_s=read_model._config.connect_timeout_s,
    )
    return ProductionPersistence(
        read_model=read_model,
        state_store_config=config,
        state_store=PostgresStateStore(config=config),
    )


__all__ = ["ProductionPersistence", "build_production_persistence"]
