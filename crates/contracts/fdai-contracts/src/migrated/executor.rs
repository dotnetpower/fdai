pub const EXECUTOR_COMMAND_TOPIC: &str = "object.executor-command";
pub const EXECUTOR_RECEIPT_TOPIC: &str = "object.executor-receipt";
pub const EXECUTOR_CONSUMER_GROUP: &str = "fdai-isolated-executor-shadow";
pub const CORE_EXECUTOR_RECEIPT_CONSUMER_GROUP: &str = "fdai-isolated-executor-client-core";
pub trait ExecutionOutcomeValue {
    fn value(&self) -> String;
}

pub trait DirectApiExecutionResultLike {
    fn action_id(&self) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["Action", "ActionStopCondition", "AzureOperationTarget", "BlastRadius", "BlastRadiusScope", "CORE_EXECUTOR_RECEIPT_CONSUMER_GROUP", "ContractBase", "EXECUTOR_COMMAND_TOPIC", "EXECUTOR_CONSUMER_GROUP", "EXECUTOR_RECEIPT_TOPIC", "DirectApiAuthenticationError", "DirectApiError", "DirectApiExecutor", "DirectApiNetworkDeniedError", "DirectApiOutcome", "DirectApiPermissionDeniedError", "DirectApiPolicyDeniedError", "DirectApiPreconditionError", "DirectApiPromotionError", "DirectApiReceipt", "DirectApiRequest", "DirectApiExecutionResultLike", "EventBus", "EventEnvelope", "ExecutionPath", "ExecutionOutcomeValue", "ExecutorCommand", "ExecutorEffectReceipt", "ExecutorEffectReceiptStatus", "ExecutorShadowReceipt", "ExecutorShadowReceiptStatus", "IdempotencyStore", "IdentityToken", "IncidentAppendStatus", "Mode", "ObservationReceipt", "ObservationReceiptStatus", "Operation", "PublishReceipt", "ResourceLock", "RollbackKind", "RollbackRef", "SafeguardBoundExecutorCommand", "SafeguardProof", "SafeguardProofBundle", "SafeguardProofKind", "AnyExecutorCommand", "StateStore", "StopConditionKind", "WorkloadIdentity", "executor_action_fingerprint", "executor_command_id_from_action_payload", "executor_action_payload_digest", "safeguard_bound_executor_command_id", "resolve_azure_operation_target"];
