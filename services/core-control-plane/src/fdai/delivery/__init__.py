"""Action delivery adapters (behind one shared interface)."""

from __future__ import annotations

from fdai.delivery.assurance_twin_remediation_bridge import (
    AssuranceTwinRemediationProposalBridge,
    TypedPipelineWhatIfProducer,
    build_reviewed_action_effect_catalog,
)
from fdai.delivery.busy_input_active_turn import (
    ActiveTurnExecutionResult,
    ActiveTurnSSEFrame,
    BusyInputActiveTurnExecutor,
)
from fdai.delivery.licensing_capability_map import (
    ActionTypeCapabilityRegistry,
    SelectiveActingLicenseDecision,
    SelectiveActingLicenseVerifier,
    TrustedTimeRollbackDetector,
    evaluate_selective_capability,
    required_license_capabilities_for_action_type,
)
from fdai.delivery.measurement.cohort_observation_export import (
    build_cohort_observation_batch,
    export_cohort_observation_batch,
)
from fdai.delivery.outbound_delivery_origin_delete import (
    InMemoryOriginDeletionAuditSink,
    OriginDeletionAuditReceipt,
    OriginDeletionAuditSink,
    OriginDeletionPreconditionError,
    OriginScopedOutboundDeliveryDeleter,
    OutboundDeliveryOriginDeleteReceipt,
)
from fdai.delivery.task_worker_completion_sink import (
    CompletionSinkDeliveryReceipt,
    DetachedSessionReplySink,
    DetachedSessionTaskWorkerCompletionSink,
    DetachedWorkerCompletionEnvelope,
    DetachedWorkerCompletionReceipt,
    InMemoryDetachedSessionReplyLedger,
    TaskWorkerCompletionSink,
)

__all__ = [
    "ActionTypeCapabilityRegistry",
    "ActiveTurnExecutionResult",
    "ActiveTurnSSEFrame",
    "AssuranceTwinRemediationProposalBridge",
    "BusyInputActiveTurnExecutor",
    "CompletionSinkDeliveryReceipt",
    "DetachedSessionReplySink",
    "DetachedSessionTaskWorkerCompletionSink",
    "DetachedWorkerCompletionEnvelope",
    "DetachedWorkerCompletionReceipt",
    "InMemoryDetachedSessionReplyLedger",
    "InMemoryOriginDeletionAuditSink",
    "OriginDeletionAuditReceipt",
    "OriginDeletionAuditSink",
    "OriginDeletionPreconditionError",
    "OriginScopedOutboundDeliveryDeleter",
    "OutboundDeliveryOriginDeleteReceipt",
    "SelectiveActingLicenseDecision",
    "SelectiveActingLicenseVerifier",
    "TaskWorkerCompletionSink",
    "TrustedTimeRollbackDetector",
    "TypedPipelineWhatIfProducer",
    "build_cohort_observation_batch",
    "build_reviewed_action_effect_catalog",
    "evaluate_selective_capability",
    "export_cohort_observation_batch",
    "required_license_capabilities_for_action_type",
]
