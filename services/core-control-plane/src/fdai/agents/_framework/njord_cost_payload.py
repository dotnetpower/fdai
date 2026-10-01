"""Njord cost-anomaly payload construction helpers."""

from __future__ import annotations

from typing import Any

from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.ontology_platform.functions import ontology_function_digest
from fdai.shared.providers.cost_governance import CostAnalysisSample, CostAnomalyAdvisory


def cost_anomaly_payload(
    finding: CostAnomalyAdvisory,
    sample: CostAnalysisSample,
) -> dict[str, Any]:
    observed_at = finding.observed_at.isoformat()
    amount_usd = float(finding.amount_usd)
    baseline_usd = float(finding.baseline_usd)
    ratio = float(finding.ratio)
    anomaly_material = {
        "target_ref": finding.resource_id,
        "scope": finding.scope_id,
        "amount_usd": amount_usd,
        "baseline_usd": baseline_usd,
        "ratio": ratio,
        "observed_at": observed_at,
        "source_authority_ref": sample.source_authority,
    }
    anomaly_digest = ontology_function_digest(anomaly_material)
    anomaly_suffix = anomaly_digest.removeprefix("sha256:")
    return {
        "id": f"cost-anomaly:{anomaly_suffix}",
        "producer_principal": "Njord",
        "correlation_id": finding.correlation_id,
        "idempotency_key": stable_idempotency_key(
            "cost-anomaly",
            finding.correlation_id,
            finding.scope_id,
            finding.resource_id,
            observed_at,
            anomaly_digest,
        ),
        "scope": finding.scope_id,
        "resource_id": finding.resource_id,
        "target_ref": finding.resource_id,
        "amount_usd": amount_usd,
        "baseline_usd": baseline_usd,
        "ratio": ratio,
        "variance": float(finding.amount_usd - finding.baseline_usd),
        "impact": float(finding.impact),
        "recommendation": finding.recommendation,
        "action_arguments": (
            {
                "target_resource_ref": finding.resource_id,
                "reason": "Cost anomaly supports the reviewed scale-down candidate.",
            }
            if finding.recommendation == "scale_down"
            else None
        ),
        "observed_at": observed_at,
        "detected_at": observed_at,
        "evidence_ref": f"cost-anomaly-evidence:{anomaly_suffix}",
        "source_authority_ref": sample.source_authority,
        "synthetic": False,
    }


__all__ = ["cost_anomaly_payload"]
