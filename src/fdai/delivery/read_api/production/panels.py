"""Production read-panel composition over durable stores."""

from __future__ import annotations

from typing import Any

from fdai.core.learning import PostTurnReviewMetrics
from fdai.core.operator_memory import OperatorMemoryReviewService
from fdai.core.scheduler import ScheduleRunHistoryService
from fdai.core.working_context import StateStoreContextSelectionEvaluationStore
from fdai.delivery.persistence import (
    PostgresAutomationBlueprintStore,
    PostgresAutomationBlueprintStoreConfig,
    PostgresMemoryCompactionRepository,
    PostgresMemoryCompactionRepositoryConfig,
    PostgresMeteringStore,
    PostgresMeteringStoreConfig,
    PostgresOperatorMemoryProposalStore,
    PostgresOperatorMemoryProposalStoreConfig,
    PostgresOperatorMemoryStore,
    PostgresOperatorMemoryStoreConfig,
    PostgresPostTurnReviewLedger,
    PostgresPostTurnReviewLedgerConfig,
    PostgresScheduleRunLedger,
    PostgresScheduleRunLedgerConfig,
    PostgresSkillProposalStore,
    PostgresSkillProposalStoreConfig,
)
from fdai.delivery.persistence.postgres_browser_evidence import (
    PostgresBrowserEvidenceArtifactStore,
    PostgresBrowserEvidenceStoreConfig,
)
from fdai.delivery.read_api.routes.automation_blueprints import AutomationBlueprintPanel
from fdai.delivery.read_api.routes.browser_evidence import BrowserEvidencePanel
from fdai.delivery.read_api.routes.context_selection_comparisons import (
    ContextSelectionComparisonPanel,
)
from fdai.delivery.read_api.routes.llm_cost import LlmCostPanel
from fdai.delivery.read_api.routes.onboarding import OnboardingPanel
from fdai.delivery.read_api.routes.operator_memory import OperatorMemoryPanel
from fdai.delivery.read_api.routes.panels import CapabilityCatalogPanel
from fdai.delivery.read_api.routes.post_turn_review_panel import PostTurnReviewPanel
from fdai.delivery.read_api.routes.scheduler_runs import SchedulerRunsPanel


def build_production_panels(
    *,
    read_model: Any,
    onboarding_probe: Any,
    onboarding_configured: bool,
    state_store: Any,
) -> tuple[Any, ...]:
    """Build the production panel set in its established order."""
    connection = {
        "dsn": read_model._config.dsn,
        "statement_timeout_ms": read_model._config.statement_timeout_ms,
        "connect_timeout_s": read_model._config.connect_timeout_s,
    }
    return (
        CapabilityCatalogPanel(),
        BrowserEvidencePanel(
            PostgresBrowserEvidenceArtifactStore(
                config=PostgresBrowserEvidenceStoreConfig(**connection)
            )
        ),
        ContextSelectionComparisonPanel(StateStoreContextSelectionEvaluationStore(state_store)),
        AutomationBlueprintPanel(
            PostgresAutomationBlueprintStore(
                config=PostgresAutomationBlueprintStoreConfig(**connection)
            )
        ),
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
        PostTurnReviewPanel(
            reviews=PostgresPostTurnReviewLedger(
                config=PostgresPostTurnReviewLedgerConfig(**connection)
            ),
            memory_proposals=PostgresOperatorMemoryProposalStore(
                config=PostgresOperatorMemoryProposalStoreConfig(**connection)
            ),
            skill_proposals=PostgresSkillProposalStore(
                config=PostgresSkillProposalStoreConfig(**connection)
            ),
            metrics=PostTurnReviewMetrics(),
            source="postgres",
            durable=True,
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
