"""Manual distillation pipeline stage.

Deterministic verification helpers for the compile-side of the rule catalog
(see ``docs/roadmap/rules-and-detection/manual-distillation.md``). The
:class:`~fdai.shared.providers.distiller.Distiller` seam (LLM-backed, fork-owned)
produces candidates; this package supplies the deterministic checks that run over
them - starting with the false-negative coverage diff.
"""

from __future__ import annotations

from fdai.rule_catalog.pipeline.distill.coverage import analyze_coverage
from fdai.rule_catalog.pipeline.distill.ontology_claims import (
    claim_text_records,
    document_content_digest,
    inventory_claims,
    reconcile_claims,
)
from fdai.rule_catalog.pipeline.distill.ontology_evaluation import (
    ChangeRiskClass,
    assess_low_risk_promotion,
    evaluate_review_package,
)
from fdai.rule_catalog.pipeline.distill.ontology_lifecycle import (
    build_projection_plan,
    plan_access_revocation,
    plan_source_retirement,
    reconcile_projection,
    record_reconciliation,
)
from fdai.rule_catalog.pipeline.distill.ontology_review import build_ontology_review_package
from fdai.rule_catalog.pipeline.distill.ontology_view import build_ontology_review_view

__all__ = [
    "analyze_coverage",
    "assess_low_risk_promotion",
    "ChangeRiskClass",
    "build_ontology_review_package",
    "build_ontology_review_view",
    "build_projection_plan",
    "claim_text_records",
    "document_content_digest",
    "evaluate_review_package",
    "inventory_claims",
    "plan_access_revocation",
    "plan_source_retirement",
    "reconcile_claims",
    "reconcile_projection",
    "record_reconciliation",
]
