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
from fdai.delivery.persistence.postgres_automation_blueprint import (
    PostgresAutomationBlueprintStore,
    PostgresAutomationBlueprintStoreConfig,
)
from fdai.delivery.persistence.postgres_background_task import (
    PostgresBackgroundTaskStore,
    PostgresBackgroundTaskStoreConfig,
)
from fdai.delivery.persistence.postgres_briefing import (
    PostgresBriefingRunStore,
    PostgresBriefingStoreConfig,
    PostgresBriefingSubscriptionStore,
    PostgresConversationPolicyStore,
)
from fdai.delivery.persistence.postgres_busy_input import (
    PostgresBusyInputStore,
    PostgresBusyInputStoreConfig,
)
from fdai.delivery.persistence.postgres_channel_identity_link import (
    PostgresChannelIdentityLinkStore,
    PostgresChannelIdentityLinkStoreConfig,
)
from fdai.delivery.persistence.postgres_channel_pairing import (
    PostgresChannelPairingStore,
    PostgresChannelPairingStoreConfig,
)
from fdai.delivery.persistence.postgres_conversation_search import (
    PostgresConversationSearch,
)
from fdai.delivery.persistence.postgres_execution_backend import (
    PostgresExecutionSubmissionLedger,
    PostgresExecutionSubmissionLedgerConfig,
)
from fdai.delivery.persistence.postgres_idempotency import (
    PostgresIdempotencyStore,
    PostgresIdempotencyStoreConfig,
)
from fdai.delivery.persistence.postgres_incident_notification import (
    PostgresIncidentNotificationDeliveryStore,
)
from fdai.delivery.persistence.postgres_incident_proposal import (
    PostgresIncidentProposalStore,
)
from fdai.delivery.persistence.postgres_jira_ledger import PostgresJiraLedger
from fdai.delivery.persistence.postgres_memory_compaction import (
    PostgresMemoryCompactionRepository,
    PostgresMemoryCompactionRepositoryConfig,
)
from fdai.delivery.persistence.postgres_metering import (
    PostgresMeteringStore,
    PostgresMeteringStoreConfig,
)
from fdai.delivery.persistence.postgres_model_health import (
    PostgresModelHealthTransitionSink,
    PostgresModelHealthTransitionSinkConfig,
)
from fdai.delivery.persistence.postgres_ontology import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
)
from fdai.delivery.persistence.postgres_operator_memory import (
    PostgresOperatorMemoryStore,
    PostgresOperatorMemoryStoreConfig,
)
from fdai.delivery.persistence.postgres_operator_memory_proposal import (
    PostgresOperatorMemoryProposalStore,
    PostgresOperatorMemoryProposalStoreConfig,
)
from fdai.delivery.persistence.postgres_outbox import (
    PostgresOutboxStore,
    PostgresOutboxStoreConfig,
)
from fdai.delivery.persistence.postgres_post_turn_review import (
    PostgresPostTurnReviewLedger,
    PostgresPostTurnReviewLedgerConfig,
)
from fdai.delivery.persistence.postgres_process_runtime import (
    PostgresProcessRuntimeStore,
    PostgresProcessRuntimeStoreConfig,
)
from fdai.delivery.persistence.postgres_programmatic_pipeline import (
    PostgresProgrammaticPipelineStore,
    PostgresProgrammaticPipelineStoreConfig,
)
from fdai.delivery.persistence.postgres_report_signal import (
    PostgresReportSignalStore,
    PostgresReportSignalStoreConfig,
)
from fdai.delivery.persistence.postgres_resource_lock import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
)
from fdai.delivery.persistence.postgres_rpc_idempotency import (
    PostgresRpcIdempotencyStore,
    PostgresRpcIdempotencyStoreConfig,
    RpcClaimConflictError,
)
from fdai.delivery.persistence.postgres_schedule_run_ledger import (
    PostgresScheduleRunLedger,
    PostgresScheduleRunLedgerConfig,
)
from fdai.delivery.persistence.postgres_scheduled_continuation import (
    PostgresScheduledContinuationStoreConfig,
    PostgresScheduledConversationAnchorStore,
)
from fdai.delivery.persistence.postgres_scheduler_store import (
    PostgresScheduleStore,
    PostgresScheduleStoreConfig,
)
from fdai.delivery.persistence.postgres_skill_proposal import (
    PostgresSkillProposalStore,
    PostgresSkillProposalStoreConfig,
)
from fdai.delivery.persistence.postgres_skill_quarantine import (
    PostgresSkillQuarantineStore,
    PostgresSkillRevocationStore,
    PostgresSkillSourceRevoker,
    PostgresSkillUpdateCandidateStore,
)
from fdai.delivery.persistence.postgres_skill_source import (
    PostgresSkillSourceRefreshStateStore,
    PostgresSkillSourceStore,
    PostgresSkillSourceStoreConfig,
)
from fdai.delivery.persistence.postgres_task_worker import (
    PostgresTaskWorkerStore,
    PostgresTaskWorkerStoreConfig,
)
from fdai.delivery.persistence.postgres_trusted_artifact import (
    PostgresTrustedArtifactStore,
    PostgresTrustedArtifactStoreConfig,
)
from fdai.delivery.persistence.postgres_user_context import (
    PostgresConversationHistoryStore,
    PostgresUserContextStoreConfig,
    PostgresUserMemoryStore,
    PostgresUserPreferenceStore,
)
from fdai.delivery.persistence.postgres_user_context_retention import (
    PostgresUserContextRetention,
    ProjectionDeleteJob,
    UserContextRetentionReport,
)
from fdai.delivery.persistence.postgres_workflow_definition import (
    PostgresWorkflowBindingStore,
    PostgresWorkflowDefinitionStore,
    PostgresWorkflowDefinitionStoreConfig,
)
from fdai.delivery.persistence.state_store_action_promotion import (
    StateStoreActionPromotionRegistry,
)
from fdai.delivery.persistence.state_store_hil_registry import (
    PostgresHilApprovalRegistry,
    StateStoreHilApprovalRegistry,
    add_pending_approval,
)

__all__ = [
    "PgVectorPatternLibrary",
    "PgVectorPatternLibraryConfig",
    "PostgresAdvisoryResourceLock",
    "PostgresAdvisoryResourceLockConfig",
    "PostgresBackgroundTaskStore",
    "PostgresBackgroundTaskStoreConfig",
    "PostgresAutomationBlueprintStore",
    "PostgresAutomationBlueprintStoreConfig",
    "PostgresBusyInputStore",
    "PostgresBusyInputStoreConfig",
    "PostgresBriefingRunStore",
    "PostgresBriefingStoreConfig",
    "PostgresBriefingSubscriptionStore",
    "PostgresChannelPairingStore",
    "PostgresChannelPairingStoreConfig",
    "PostgresChannelIdentityLinkStore",
    "PostgresChannelIdentityLinkStoreConfig",
    "PostgresConversationHistoryStore",
    "PostgresConversationSearch",
    "PostgresConversationPolicyStore",
    "PostgresExecutionSubmissionLedger",
    "PostgresExecutionSubmissionLedgerConfig",
    "PostgresIdempotencyStore",
    "PostgresIdempotencyStoreConfig",
    "PostgresIncidentProposalStore",
    "PostgresJiraLedger",
    "PostgresMeteringStore",
    "PostgresMeteringStoreConfig",
    "PostgresMemoryCompactionRepository",
    "PostgresMemoryCompactionRepositoryConfig",
    "PostgresModelHealthTransitionSink",
    "PostgresModelHealthTransitionSinkConfig",
    "PostgresIncidentNotificationDeliveryStore",
    "PostgresOperatorMemoryStore",
    "PostgresOperatorMemoryStoreConfig",
    "PostgresOperatorMemoryProposalStore",
    "PostgresOperatorMemoryProposalStoreConfig",
    "PostgresOntologyInstanceStore",
    "PostgresOntologyInstanceStoreConfig",
    "PostgresOutboxStore",
    "PostgresOutboxStoreConfig",
    "PostgresProcessRuntimeStore",
    "PostgresProcessRuntimeStoreConfig",
    "PostgresProgrammaticPipelineStore",
    "PostgresProgrammaticPipelineStoreConfig",
    "PostgresPostTurnReviewLedger",
    "PostgresPostTurnReviewLedgerConfig",
    "PostgresReportSignalStore",
    "PostgresReportSignalStoreConfig",
    "PostgresRpcIdempotencyStore",
    "PostgresRpcIdempotencyStoreConfig",
    "PostgresScheduleStore",
    "PostgresScheduleStoreConfig",
    "PostgresScheduleRunLedger",
    "PostgresScheduleRunLedgerConfig",
    "PostgresScheduledContinuationStoreConfig",
    "PostgresScheduledConversationAnchorStore",
    "PostgresSkillProposalStore",
    "PostgresSkillProposalStoreConfig",
    "PostgresSkillQuarantineStore",
    "PostgresSkillRevocationStore",
    "PostgresSkillSourceRefreshStateStore",
    "PostgresSkillSourceRevoker",
    "PostgresSkillSourceStore",
    "PostgresSkillSourceStoreConfig",
    "PostgresSkillUpdateCandidateStore",
    "PostgresTrustedArtifactStore",
    "PostgresTrustedArtifactStoreConfig",
    "PostgresTaskWorkerStore",
    "PostgresTaskWorkerStoreConfig",
    "PostgresStateStore",
    "PostgresStateStoreConfig",
    "PostgresUserContextStoreConfig",
    "PostgresUserMemoryStore",
    "PostgresUserPreferenceStore",
    "PostgresUserContextRetention",
    "ProjectionDeleteJob",
    "UserContextRetentionReport",
    "PostgresWorkflowBindingStore",
    "PostgresWorkflowDefinitionStore",
    "PostgresWorkflowDefinitionStoreConfig",
    "RpcClaimConflictError",
    "PostgresHilApprovalRegistry",
    "StateStoreHilApprovalRegistry",
    "StateStoreActionPromotionRegistry",
    "add_pending_approval",
]
