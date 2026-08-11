"""Concrete provider adapters owned by the independent Operator Service."""

from fdai_operator_service.adapters.local_narrator import LocalAzureNarratorAdapters
from fdai_operator_service.adapters.semantic_kafka import (
    OperatorSemanticKafkaBus,
    OperatorSemanticKafkaConfig,
)

__all__ = [
    "LocalAzureNarratorAdapters",
    "OperatorSemanticKafkaBus",
    "OperatorSemanticKafkaConfig",
]
