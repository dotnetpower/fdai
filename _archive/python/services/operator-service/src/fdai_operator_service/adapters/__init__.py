"""Concrete provider adapters owned by the independent Operator Service."""

from fdai_operator_service.adapters.azure_identity import create_workload_credential
from fdai_operator_service.adapters.live_stage_kafka import (
    LiveStageKafkaConfig,
    LiveStageKafkaRelay,
)
from fdai_operator_service.adapters.local_narrator import (
    LocalAzureNarratorAdapters,
    StartupOwnedLocalAzureNarratorAdapters,
)
from fdai_operator_service.adapters.semantic_kafka import (
    OperatorSemanticKafkaBus,
    OperatorSemanticKafkaConfig,
)

__all__ = [
    "LiveStageKafkaConfig",
    "LiveStageKafkaRelay",
    "LocalAzureNarratorAdapters",
    "OperatorSemanticKafkaBus",
    "OperatorSemanticKafkaConfig",
    "StartupOwnedLocalAzureNarratorAdapters",
    "create_workload_credential",
]
