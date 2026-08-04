"""Production read-panel composition over durable stores."""

from __future__ import annotations

from typing import Any

from fdai.core.learning import PostTurnReviewMetrics
from fdai.core.operator_memory import OperatorMemoryReviewService
from fdai.core.scheduler import ScheduleRunHistoryService
from fdai.core.working_context import StateStoreContextSelectionEvaluationStore
from fdai.delivery.operator_api.routes.audit_finops import AuditFinOpsPanel
from fdai.delivery.operator_api.routes.audit_measurement_summary import (
    AuditAutonomyMeasurementPanel,
)
from fdai.delivery.operator_api.routes.automation_blueprints import AutomationBlueprintPanel
from fdai.delivery.operator_api.routes.browser_evidence import BrowserEvidencePanel
from fdai.delivery.operator_api.routes.context_selection_comparisons import (
    ContextSelectionComparisonPanel,
)
from fdai.delivery.operator_api.routes.dynamic_assurance import DynamicAssurancePanel
from fdai.delivery.operator_api.routes.forecast_learning import ForecastLearningPanel
from fdai.delivery.operator_api.routes.llm_cost import LlmCostPanel
from fdai.delivery.operator_api.routes.onboarding import OnboardingPanel
from fdai.delivery.operator_api.routes.operator_memory import OperatorMemoryPanel
from fdai.delivery.operator_api.routes.panels import CapabilityCatalogPanel
from fdai.delivery.operator_api.routes.persisted_promotion_gates import (
    PersistedPromotionGatesPanel,
)
from fdai.delivery.operator_api.routes.post_turn_review_panel import PostTurnReviewPanel
from fdai.delivery.operator_api.routes.scheduler_runs import SchedulerRunsPanel
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
from fdai.delivery.persistence.postgres_forecast_episode import (
    PostgresForecastEpisodeStore,
    PostgresForecastEpisodeStoreConfig,
)


def build_production_panels(
    *,
    read_model: Any,
    onboarding_probe: Any,
    onboarding_configured: bool,
    state_store: Any,
    action_types: tuple[Any, ...],
    active_rule_count: int,
) -> tuple[Any, ...]:
    """Build the production panel set in its established order."""
    connection = {
        "dsn": read_model._config.dsn,
        "statement_timeout_ms": read_model._config.statement_timeout_ms,
        "connect_timeout_s": read_model._config.connect_timeout_s,
    }
    return (
        CapabilityCatalogPanel(),
        AuditFinOpsPanel(read_model),
        AuditAutonomyMeasurementPanel(
            read_model,
            active_rule_count=active_rule_count,
        ),
        PersistedPromotionGatesPanel(
            action_types=action_types,
            store=state_store,
        ),
        BrowserEvidencePanel(
            PostgresBrowserEvidenceArtifactStore(
                config=PostgresBrowserEvidenceStoreConfig(**connection)
            )
        ),
        ContextSelectionComparisonPanel(StateStoreContextSelectionEvaluationStore(state_store)),
        DynamicAssurancePanel(state_store),
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
        ForecastLearningPanel(
            PostgresForecastEpisodeStore(config=PostgresForecastEpisodeStoreConfig(**connection))
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
