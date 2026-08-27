"""Ontology-grounded impact analysis for governed interventions."""

from fdai.core.impact_analysis.analyzer import ImpactAnalyzer, ImpactTraversalBounds
from fdai.core.impact_analysis.change_assessment import (
    ChangeAssessment,
    ChangeAssessmentService,
    ChangeAssessmentUnavailableError,
    GraphFreshnessReceipt,
    GraphFreshnessReceiptSource,
    build_graph_freshness_receipt,
)
from fdai.core.impact_analysis.compiler import compile_impact_envelope
from fdai.core.impact_analysis.models import (
    AffectedSet,
    ImpactEnvelopeRecord,
    ObjectiveBound,
    TelemetryRequirements,
)
from fdai.core.impact_analysis.projection import ImpactEnvelopeProjector

__all__ = [
    "AffectedSet",
    "build_graph_freshness_receipt",
    "ChangeAssessment",
    "ChangeAssessmentService",
    "ChangeAssessmentUnavailableError",
    "compile_impact_envelope",
    "ImpactAnalyzer",
    "ImpactEnvelopeRecord",
    "ImpactEnvelopeProjector",
    "ImpactTraversalBounds",
    "GraphFreshnessReceipt",
    "GraphFreshnessReceiptSource",
    "ObjectiveBound",
    "TelemetryRequirements",
]
