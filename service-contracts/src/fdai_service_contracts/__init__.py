"""Implementation-free service identity and release contracts."""

from fdai_service_contracts.compatibility import (
    CompatibilityError,
    DeliveryResult,
    SemVer,
    assert_additive_schema,
    canonical_digest,
    ensure_supported_version,
    load_json_object,
    matrix_digest,
    project_additive_fields,
    validate_delivery_trace,
    validate_peer_upgrade_receipt,
)
from fdai_service_contracts.descriptor import ServiceDescriptor, ServiceKind
from fdai_service_contracts.executor import (
    CORE_EXECUTOR_RECEIPT_CONSUMER_GROUP,
    EXECUTOR_COMMAND_TOPIC,
    EXECUTOR_CONSUMER_GROUP,
    EXECUTOR_RECEIPT_TOPIC,
    DirectApiExecutionResultLike,
    ExecutionOutcomeValue,
)
from fdai_service_contracts.manifest import CompatibilitySummary, validate_manifest

__all__ = [
    "CORE_EXECUTOR_RECEIPT_CONSUMER_GROUP",
    "EXECUTOR_COMMAND_TOPIC",
    "EXECUTOR_CONSUMER_GROUP",
    "EXECUTOR_RECEIPT_TOPIC",
    "CompatibilityError",
    "CompatibilitySummary",
    "DeliveryResult",
    "DirectApiExecutionResultLike",
    "ExecutionOutcomeValue",
    "SemVer",
    "ServiceDescriptor",
    "ServiceKind",
    "assert_additive_schema",
    "canonical_digest",
    "ensure_supported_version",
    "load_json_object",
    "matrix_digest",
    "project_additive_fields",
    "validate_delivery_trace",
    "validate_manifest",
    "validate_peer_upgrade_receipt",
]
