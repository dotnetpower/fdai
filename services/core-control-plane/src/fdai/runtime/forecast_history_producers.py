"""Compose reviewed forecast history producers onto their authoritative source readers.

Only sources with a bounded, read-only reader over an existing owner's records are bound:
Thor/Saga actions read the state-store audit chain, external changes read the inventory journal
witness, excluded windows read retained operating-intent ChangeWindow revisions, and resource
lifecycle reads the confirmed-tombstone incarnation ledger.
"""

from __future__ import annotations

from fdai.core.detection.forecast_history_producer import ForecastHistoryProducer
from fdai.core.detection.forecast_history_source import ForecastHistorySource
from fdai.core.ontology_platform.state_transitions import StateTransitionStore
from fdai.delivery.forecast_change_history import ForecastChangeHistoryWitness
from fdai.delivery.forecast_history_configuration import ForecastHistoryConfiguration
from fdai.delivery.forecast_history_sources import (
    ActionAuditHistorySource,
    ChangeWindowHistorySource,
    IncarnationLifecycleHistorySource,
    JournalChangeHistorySource,
)
from fdai.delivery.persistence.postgres_forecast_action_history import (
    PostgresForecastActionHistoryConfig,
    PostgresForecastActionHistoryReader,
)
from fdai.delivery.persistence.postgres_forecast_change_history import (
    PostgresForecastChangeHistoryConfig,
    PostgresForecastChangeHistoryReader,
)
from fdai.delivery.persistence.postgres_forecast_change_window_history import (
    PostgresForecastChangeWindowHistoryConfig,
    PostgresForecastChangeWindowHistoryReader,
)
from fdai.delivery.persistence.postgres_forecast_lifecycle_history import (
    PostgresForecastLifecycleHistoryConfig,
    PostgresForecastLifecycleHistoryReader,
)


def build_forecast_history_producers(
    *, dsn: str, configuration: ForecastHistoryConfiguration, store: StateTransitionStore
) -> tuple[ForecastHistoryProducer, ...]:
    """Bind each validated producer to exactly one read-only source reader."""
    producers: list[ForecastHistoryProducer] = []
    for binding, history in configuration.producers:
        source: ForecastHistorySource
        if binding.kind == "actions":
            source = ActionAuditHistorySource(
                reader=PostgresForecastActionHistoryReader(
                    config=PostgresForecastActionHistoryConfig(
                        dsn=dsn, statement_timeout_ms=1_000, connect_timeout_s=1
                    )
                )
            )
        elif binding.kind == "changes":
            source = JournalChangeHistorySource(
                witness=ForecastChangeHistoryWitness(
                    reader=PostgresForecastChangeHistoryReader(
                        config=PostgresForecastChangeHistoryConfig(
                            dsn=dsn, statement_timeout_ms=1_000, connect_timeout_s=1
                        )
                    )
                ),
                scope_ref=binding.source_scope_ref,
            )
        elif binding.kind == "excluded_windows":
            source = ChangeWindowHistorySource(
                reader=PostgresForecastChangeWindowHistoryReader(
                    config=PostgresForecastChangeWindowHistoryConfig(
                        dsn=dsn, statement_timeout_ms=1_000, connect_timeout_s=1
                    )
                )
            )
        elif binding.kind == "resource_lifecycle":
            source = IncarnationLifecycleHistorySource(
                reader=PostgresForecastLifecycleHistoryReader(
                    config=PostgresForecastLifecycleHistoryConfig(
                        dsn=dsn, statement_timeout_ms=1_000, connect_timeout_s=1
                    )
                )
            )
        else:
            raise ValueError(f"forecast history {binding.kind} producer source is unavailable")
        producers.append(
            ForecastHistoryProducer(binding=binding, history=history, source=source, store=store)
        )
    return tuple(producers)


__all__ = ["build_forecast_history_producers"]
