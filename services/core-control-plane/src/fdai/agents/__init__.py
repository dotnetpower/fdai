"""FDAI pantheon runtime.

The pantheon is a fixed upstream set of 15 named agents that own the
runtime control plane. This package exposes the agent contract, the
registry, and the topic naming convention. Behavior for individual
agents lands wave-by-wave (see
`docs/roadmap/agents/agent-pantheon-implementation.md`); Wave 1 ships the
scaffolding only. Catalog-backed action semantics are exported here for
composition and replay callers without exposing private framework modules.

Design authority: `docs/roadmap/agents/agent-pantheon.md`.
"""

from fdai.agents._framework.action_run_identity import (
    action_run_identity_digest as action_run_identity_digest,
)
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.adapters import (
    AdminCard,
    AdminNotificationAdapter,
    AuditEntry,
    GitHubIssue,
    IdempotentIssueTrackerAdapter,
    InMemoryAuditChain,
    IssueTrackerAdapter,
)
from fdai.agents._framework.anomaly_action import (
    AnomalyActionCandidate as AnomalyActionCandidate,
)
from fdai.agents._framework.anomaly_action import (
    AnomalyActionPreparation as AnomalyActionPreparation,
)
from fdai.agents._framework.anomaly_action import (
    AnomalyActionPreparer as AnomalyActionPreparer,
)
from fdai.agents._framework.anomaly_action import (
    AnomalyActionSource as AnomalyActionSource,
)
from fdai.agents._framework.approval_readback import (
    read_current_action_approval as read_current_action_approval,
)
from fdai.agents._framework.assignment_wiring import AssignmentWorkflowBindings
from fdai.agents._framework.audit_chain_migration import (
    SagaAuditMigration as SagaAuditMigration,
)
from fdai.agents._framework.audit_chain_migration import (
    prepare_saga_audit_migration as prepare_saga_audit_migration,
)
from fdai.agents._framework.base import (
    Agent,
    AgentSpec,
    ConversationCharter,
    ConversationTool,
    Layer,
)
from fdai.agents._framework.bragi_intent_training import (
    IntentTrainingEvaluationResult,
    IntentTrainingEvaluator,
    IntentTrainingEvidence,
    IntentTrainingRun,
    ReviewedIntentTrainingPromotion,
)
from fdai.agents._framework.bus import InMemoryBus, PantheonBus
from fdai.agents._framework.bus_bridge import (
    AgentHandlerObserver,
    AgentHandlerPhase,
    EventBusBridge,
)
from fdai.agents._framework.catalog_review_wiring import CatalogReviewBindings
from fdai.agents._framework.conversation_prompt import (
    BASELINE_LAYER_IDS,
    CONSTRAINT_LAYER_IDS,
    ComposedConversationPrompt,
    ConversationSituation,
)
from fdai.agents._framework.conversation_tools import AgentToolResult, AgentToolStatus
from fdai.agents._framework.cross_vertical_candidates import (
    validate_cross_vertical_candidate,
)
from fdai.agents._framework.deliberation import (
    ConversationDeliberator,
    ConversationSynthesisVerifier,
    DeliberationClaim,
    DeliberationRequest,
    SynthesisOutcome,
    SynthesisVerification,
    T2ConversationSynthesizer,
)
from fdai.agents._framework.development_authority_runtime import (
    ApprovalRuntimeBindings,
    DevelopmentRuntimeBindings,
)
from fdai.agents._framework.divergence import ShadowDivergenceLedger
from fdai.agents._framework.document_intent import publish_document_intent_source
from fdai.agents._framework.factory import (
    DEFAULT_COST_RUNTIME_BINDINGS,
    CostRuntimeBindings,
    instantiate_pantheon,
)
from fdai.agents._framework.forseti_baseline_evaluation import (
    BASELINE_EVALUATION_COMPLETION_PREFIX,
    BASELINE_EVALUATION_OUTCOME_PREFIX,
    BaselineEvaluationAuditReference,
    record_baseline_evaluation,
)
from fdai.agents._framework.forseti_baseline_worker import (
    BASELINE_EVALUATION_CLAIM_PREFIX,
    BASELINE_EVALUATION_COVERAGE_PREFIX,
    BaselineWorkerLimits,
    BaselineWorkerResult,
    ForsetiBaselineScheduler,
    ForsetiBaselineWorker,
)
from fdai.agents._framework.forseti_historical_replay import (
    ForsetiHistoricalQualitySample,
    ForsetiHistoricalReplay,
    ForsetiHistoricalReplaySource,
)
from fdai.agents._framework.freyr_sampling import MAX_RECURRING_SAMPLES, UtilizationSample
from fdai.agents._framework.huginn_operator_receipt import (
    OperatorRequestReceiptGate,
    ReservedOperatorRequestReceipt,
)
from fdai.agents._framework.introspection import agent_state_evidence_ref
from fdai.agents._framework.loki_adversarial import (
    MAX_GENERATED_SCENARIOS,
    ChaosScenarioCandidate,
    ChaosScenarioGenerator,
    frozen_corpus_key,
)
from fdai.agents._framework.loki_scheduling import (
    ChaosScheduleConfig,
)
from fdai.agents._framework.loki_scheduling import (
    validate_config as validate_chaos_schedule,
)
from fdai.agents._framework.mimir_maintenance import (
    MimirCatalogPromotionOutcome,
    MimirCatalogPromotionOutcomeReader,
    MimirDeprecationCandidate,
    MimirRegressionResult,
    MimirRegressionRunner,
    MimirRuleDeprecationReader,
    MimirRuleSourcePollResult,
)
from fdai.agents._framework.mimir_policy_administration import (
    POLICY_ADMIN_OPA_CAPABILITIES_RELATIVE,
    MimirPolicyAdministration,
    OpaRegoPolicyCompiler,
    StateStorePolicyRevisionStore,
)
from fdai.agents._framework.muninn_investigation_strategy import (
    MuninnInvestigationStrategyCohortSink,
)
from fdai.agents._framework.ontology_index import (
    ContextIndexMessage,
    ContextIndexWorkerBindings,
    recover_context_index_publications,
)
from fdai.agents._framework.owned_answer import compose_owned_answer
from fdai.agents._framework.pantheon import (
    HARD_DEPENDENCY_AGENTS,
    LLM_HOT_PATH_ALLOWLIST,
    PANTHEON_NAMES,
    PANTHEON_SPECS,
)
from fdai.agents._framework.prompt_audit import PromptAuditResult, audit_agent_prompt
from fdai.agents._framework.provider_adapters import (
    StateStoreActionRunStore,
    StateStoreAuditChainAdapter,
)
from fdai.agents._framework.registry import PantheonRegistry, load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents._framework.runtime_health import (
    bind_availability_probe,
    evaluate_degradation,
)
from fdai.agents._framework.runtime_payload_validation import (
    default_payload_validator as default_payload_validator,
)
from fdai.agents._framework.runtime_subscriptions import (
    RECOVERY_EFFECT_OBSERVATION_TOPIC,
    RECOVERY_EFFECT_OBSERVER_PRINCIPAL,
    RuleGenerationWorkerBindings,
    bind_recovery_effect_observation,
)
from fdai.agents._framework.semantic_routing import SemanticRouterConfig
from fdai.agents._framework.state_store_issue_tracker import (
    StateStoreIssueTrackerAdapter,
)
from fdai.agents._framework.thor_action_run import ActionRun
from fdai.agents._framework.thor_preflight import (
    CompositeThorPreflightSimulator,
    PreflightSimulationResult,
    ThorPreflightSimulator,
)
from fdai.agents._framework.tool_planner import (
    MAX_TOOL_PLANS,
    ConversationToolPlan,
    plan_conversation_tools,
)
from fdai.agents._framework.tool_semantic import SemanticToolConfig, SemanticToolPlanner
from fdai.agents._framework.topics import (
    ENVELOPE_SCHEMA_VERSION,
    OWNED_OBJECT_TOPICS,
    partition_key_for,
    stable_idempotency_key,
    topic_for_object_type,
)
from fdai.agents._framework.var_final_approval import (
    validate_final_record as validate_final_approval_record,
)
from fdai.agents._framework.var_kill_switch import (
    KillSwitchRequestRejectedError,
    VarKillSwitchRequestHandler,
)
from fdai.agents._framework.var_ticket_identity import approval_state_key
from fdai.agents._framework.var_ticket_identity import (
    approval_state_key as action_approval_state_key,
)
from fdai.agents._framework.vertical_precedence import InitialVerticalPrecedence
from fdai.agents._framework.workflows import WORKFLOWS, WorkflowSpec
from fdai.agents.bragi import Bragi
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.mimir import Mimir
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RuleGenerationBuildRequestEvent,
)


async def request_rule_generation(
    runtime: PantheonRuntime,
    request: RuleGenerationBuildRequestEvent,
) -> None:
    """Route one production reconciliation request through Mimir's typed port."""

    mimir = runtime.agents.get("Mimir")
    if not isinstance(mimir, Mimir):
        raise RuntimeError("Mimir Rule generation ingress is unavailable")
    await mimir.request_rule_generation(request)


async def request_context_index(runtime: PantheonRuntime, request: ContextIndexMessage) -> None:
    """Publish one typed reconciliation request through the Huginn-owned ingress topic."""
    request = ContextIndexMessage.model_validate_json(request.model_dump_json())
    if request.phase not in {"prepare", "transition"} or "Huginn" not in runtime.agents:
        raise ValueError("ontology ContextIndex reconciliation requires available Huginn ingress")
    await runtime.bridge.publish("Huginn", request.topic, request.model_dump(mode="json"))


__all__ = [
    "action_run_identity_digest",
    "action_approval_state_key",
    "validate_final_approval_record",
    "default_payload_validator",
    "publish_document_intent_source",
    "approval_state_key",
    "BASELINE_EVALUATION_CLAIM_PREFIX",
    "BASELINE_EVALUATION_COMPLETION_PREFIX",
    "BASELINE_EVALUATION_COVERAGE_PREFIX",
    "BASELINE_EVALUATION_OUTCOME_PREFIX",
    "BaselineEvaluationAuditReference",
    "BaselineWorkerLimits",
    "BaselineWorkerResult",
    "ForsetiBaselineScheduler",
    "ForsetiBaselineWorker",
    "record_baseline_evaluation",
    "ContextIndexMessage",
    "ContextIndexWorkerBindings",
    "request_context_index",
    "recover_context_index_publications",
    "ActionSemanticsCatalog",
    "ActionRun",
    "AssignmentWorkflowBindings",
    "Agent",
    "Forseti",
    "ForsetiHistoricalQualitySample",
    "ForsetiHistoricalReplay",
    "ForsetiHistoricalReplaySource",
    "AdminCard",
    "AdminNotificationAdapter",
    "AuditEntry",
    "BASELINE_LAYER_IDS",
    "CONSTRAINT_LAYER_IDS",
    "AgentHandlerObserver",
    "AgentHandlerPhase",
    "AgentSpec",
    "MAX_TOOL_PLANS",
    "MuninnInvestigationStrategyCohortSink",
    "POLICY_ADMIN_OPA_CAPABILITIES_RELATIVE",
    "AgentToolResult",
    "AgentToolStatus",
    "ApprovalRuntimeBindings",
    "ConversationToolPlan",
    "SemanticToolConfig",
    "SemanticToolPlanner",
    "agent_state_evidence_ref",
    "audit_agent_prompt",
    "bind_availability_probe",
    "Bragi",
    "CatalogReviewBindings",
    "ChaosScheduleConfig",
    "ChaosScenarioCandidate",
    "ChaosScenarioGenerator",
    "ComposedConversationPrompt",
    "ConversationCharter",
    "ConversationDeliberator",
    "ConversationSituation",
    "ConversationTool",
    "CompositeThorPreflightSimulator",
    "CostRuntimeBindings",
    "DEFAULT_COST_RUNTIME_BINDINGS",
    "DevelopmentRuntimeBindings",
    "DeliberationClaim",
    "DeliberationRequest",
    "EventBusBridge",
    "Heimdall",
    "Huginn",
    "ENVELOPE_SCHEMA_VERSION",
    "GitHubIssue",
    "IdempotentIssueTrackerAdapter",
    "IssueTrackerAdapter",
    "Layer",
    "KillSwitchRequestRejectedError",
    "Mimir",
    "MimirCatalogPromotionOutcome",
    "MimirCatalogPromotionOutcomeReader",
    "MimirDeprecationCandidate",
    "MimirPolicyAdministration",
    "MimirRegressionResult",
    "MimirRegressionRunner",
    "MimirRuleDeprecationReader",
    "MimirRuleSourcePollResult",
    "MAX_RECURRING_SAMPLES",
    "MAX_GENERATED_SCENARIOS",
    "UtilizationSample",
    "VarKillSwitchRequestHandler",
    "Norns",
    "OperatorRequestReceiptGate",
    "OpaRegoPolicyCompiler",
    "ReservedOperatorRequestReceipt",
    "PantheonBus",
    "InMemoryBus",
    "InMemoryAuditChain",
    "IntentTrainingEvaluationResult",
    "IntentTrainingEvaluator",
    "IntentTrainingEvidence",
    "IntentTrainingRun",
    "PantheonRegistry",
    "PantheonRuntime",
    "PromptAuditResult",
    "PreflightSimulationResult",
    "RECOVERY_EFFECT_OBSERVATION_TOPIC",
    "RECOVERY_EFFECT_OBSERVER_PRINCIPAL",
    "RuleGenerationWorkerBindings",
    "ReviewedIntentTrainingPromotion",
    "Saga",
    "SemanticRouterConfig",
    "ShadowDivergenceLedger",
    "StateStoreActionRunStore",
    "StateStoreAuditChainAdapter",
    "StateStorePolicyRevisionStore",
    "StateStoreIssueTrackerAdapter",
    "SynthesisOutcome",
    "SynthesisVerification",
    "ConversationSynthesisVerifier",
    "T2ConversationSynthesizer",
    "ThorPreflightSimulator",
    "bind_recovery_effect_observation",
    "plan_conversation_tools",
    "compose_owned_answer",
    "request_rule_generation",
    "load_pantheon",
    "instantiate_pantheon",
    "evaluate_degradation",
    "InitialVerticalPrecedence",
    "PANTHEON_SPECS",
    "PANTHEON_NAMES",
    "HARD_DEPENDENCY_AGENTS",
    "LLM_HOT_PATH_ALLOWLIST",
    "OWNED_OBJECT_TOPICS",
    "topic_for_object_type",
    "partition_key_for",
    "stable_idempotency_key",
    "validate_chaos_schedule",
    "validate_cross_vertical_candidate",
    "frozen_corpus_key",
    "WORKFLOWS",
    "WorkflowSpec",
]
