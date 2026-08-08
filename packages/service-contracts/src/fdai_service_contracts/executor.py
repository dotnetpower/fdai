"""Implementation-free contracts for the isolated Executor service boundary."""

from __future__ import annotations

from typing import Protocol

from fdai_service_contracts.executor_models import (
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    ContractBase,
    ExecutionPath,
    ExecutorCommand,
    ExecutorEffectReceipt,
    ExecutorEffectReceiptStatus,
    ExecutorShadowReceipt,
    ExecutorShadowReceiptStatus,
    Mode,
    Operation,
    RollbackKind,
    RollbackRef,
    StopConditionKind,
    executor_action_payload_digest,
)
from fdai_service_contracts.executor_providers import (
    DirectApiAuthenticationError,
    DirectApiError,
    DirectApiExecutor,
    DirectApiNetworkDeniedError,
    DirectApiOutcome,
    DirectApiPermissionDeniedError,
    DirectApiPolicyDeniedError,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
    EventBus,
    EventEnvelope,
    IdempotencyStore,
    IdentityToken,
    IncidentAppendStatus,
    PublishReceipt,
    ResourceLock,
    StateStore,
    WorkloadIdentity,
)
from fdai_service_contracts.executor_targets import (
    AzureOperationTarget,
    resolve_azure_operation_target,
)

EXECUTOR_COMMAND_TOPIC = "object.executor-command"
EXECUTOR_RECEIPT_TOPIC = "object.executor-receipt"
EXECUTOR_CONSUMER_GROUP = "fdai-isolated-executor-shadow"
CORE_EXECUTOR_RECEIPT_CONSUMER_GROUP = "fdai-isolated-executor-client-core"


class ExecutionOutcomeValue(Protocol):
    """Expose one stable terminal outcome value without owning its enum."""

    @property
    def value(self) -> str:
        """Return the serialized terminal outcome."""

        ...


class DirectApiExecutionResultLike(Protocol):
    """Result shape accepted from a guarded direct-API effect executor."""

    @property
    def action_id(self) -> str: ...

    @property
    def outcome(self) -> ExecutionOutcomeValue: ...

    @property
    def receipt_ref(self) -> str | None: ...

    @property
    def rollback_succeeded(self) -> bool | None: ...

    @property
    def reason(self) -> str | None: ...


__all__ = [
    "Action",
    "ActionStopCondition",
    "AzureOperationTarget",
    "BlastRadius",
    "BlastRadiusScope",
    "CORE_EXECUTOR_RECEIPT_CONSUMER_GROUP",
    "ContractBase",
    "EXECUTOR_COMMAND_TOPIC",
    "EXECUTOR_CONSUMER_GROUP",
    "EXECUTOR_RECEIPT_TOPIC",
    "DirectApiAuthenticationError",
    "DirectApiError",
    "DirectApiExecutor",
    "DirectApiNetworkDeniedError",
    "DirectApiOutcome",
    "DirectApiPermissionDeniedError",
    "DirectApiPolicyDeniedError",
    "DirectApiPreconditionError",
    "DirectApiPromotionError",
    "DirectApiReceipt",
    "DirectApiRequest",
    "DirectApiExecutionResultLike",
    "EventBus",
    "EventEnvelope",
    "ExecutionPath",
    "ExecutionOutcomeValue",
    "ExecutorCommand",
    "ExecutorEffectReceipt",
    "ExecutorEffectReceiptStatus",
    "ExecutorShadowReceipt",
    "ExecutorShadowReceiptStatus",
    "IdempotencyStore",
    "IdentityToken",
    "IncidentAppendStatus",
    "Mode",
    "Operation",
    "PublishReceipt",
    "ResourceLock",
    "RollbackKind",
    "RollbackRef",
    "StateStore",
    "StopConditionKind",
    "WorkloadIdentity",
    "executor_action_payload_digest",
    "resolve_azure_operation_target",
]
