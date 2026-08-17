"""Concrete provider adapters owned by the independent Operator Service."""

from fdai_operator_service.adapters.live_stage_kafka import (
    LiveStageKafkaConfig,
    LiveStageKafkaRelay,
)
from fdai_operator_service.adapters.local_narrator import LocalAzureNarratorAdapters
from fdai_operator_service.adapters.semantic_kafka import (
    OperatorSemanticKafkaBus,
    OperatorSemanticKafkaConfig,
)
from fdai_operator_service.adapters.subscription_scope import AzureSubscriptionScopeProvider

__all__ = [
    "LiveStageKafkaConfig",
    "LiveStageKafkaRelay",
    "LocalAzureNarratorAdapters",
    "OperatorSemanticKafkaBus",
    "OperatorSemanticKafkaConfig",
    "AzureSubscriptionScopeProvider",
]
