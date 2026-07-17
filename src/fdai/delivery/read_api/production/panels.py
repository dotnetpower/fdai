"""Production read-panel composition over durable stores."""

from __future__ import annotations

from typing import Any

from fdai.core.operator_memory import OperatorMemoryReviewService
from fdai.core.scheduler import ScheduleRunHistoryService
from fdai.delivery.persistence import (
    PostgresMemoryCompactionRepository,
    PostgresMemoryCompactionRepositoryConfig,
    PostgresMeteringStore,
    PostgresMeteringStoreConfig,
    PostgresOperatorMemoryStore,
    PostgresOperatorMemoryStoreConfig,
    PostgresScheduleRunLedger,
    PostgresScheduleRunLedgerConfig,
)
from fdai.delivery.read_api.routes.llm_cost import LlmCostPanel
from fdai.delivery.read_api.routes.onboarding import OnboardingPanel
from fdai.delivery.read_api.routes.operator_memory import OperatorMemoryPanel
from fdai.delivery.read_api.routes.panels import CapabilityCatalogPanel
from fdai.delivery.read_api.routes.scheduler_runs import SchedulerRunsPanel


def build_production_panels(
    *, read_model: Any, onboarding_probe: Any, onboarding_configured: bool
) -> tuple[Any, ...]:
    """Build the production panel set in its established order."""
    connection = {
        "dsn": read_model._config.dsn,
        "statement_timeout_ms": read_model._config.statement_timeout_ms,
        "connect_timeout_s": read_model._config.connect_timeout_s,
    }
    return (
        CapabilityCatalogPanel(),
        OperatorMemoryPanel(
            service=OperatorMemoryReviewService(
                store=PostgresOperatorMemoryStore(
                    config=PostgresOperatorMemoryStoreConfig(**connection)
                )
            ),
            compactions=PostgresMemoryCompactionRepository(
                config=PostgresMemoryCompactionRepositoryConfig(**connection)
            ),
        ),
        SchedulerRunsPanel(
            service=ScheduleRunHistoryService(
                ledger=PostgresScheduleRunLedger(
                    config=PostgresScheduleRunLedgerConfig(**connection)
                )
            ),
            source="postgres",
            durable=True,
        ),
        OnboardingPanel(
            probe=onboarding_probe,
            configured=onboarding_configured,
        ),
        LlmCostPanel(PostgresMeteringStore(config=PostgresMeteringStoreConfig(**connection))),
    )


__all__ = ["build_production_panels"]
