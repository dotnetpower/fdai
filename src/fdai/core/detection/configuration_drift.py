"""Public facade for deterministic frozen configuration drift checks."""

from fdai.core.detection.configuration_drift_compare import compare_configuration
from fdai.core.detection.configuration_drift_models import (
    ConfigurationDriftReport,
    ConfigurationLink,
    ConfigurationObservation,
    ConfigurationResource,
    DriftFinding,
    DriftType,
    DriftVerdict,
    EvidenceCompleteness,
    FrozenConfigurationBaseline,
    KnowledgeGroundingStatus,
)

__all__ = [
    "ConfigurationDriftReport",
    "ConfigurationLink",
    "ConfigurationObservation",
    "ConfigurationResource",
    "DriftFinding",
    "DriftType",
    "DriftVerdict",
    "EvidenceCompleteness",
    "FrozenConfigurationBaseline",
    "KnowledgeGroundingStatus",
    "compare_configuration",
]
