"""Repository-safe projection of governed cohort claim results."""

from __future__ import annotations

from typing import Any

from fdai.core.measurement.cohort_claim_policy import CohortClaimPolicy
from fdai_service_contracts.baseline_cohort import (
    BaselineTreatmentCohortReceipt,
    CohortArmReport,
    CohortClaimAssessment,
)


def cohort_claim_record(
    policy: CohortClaimPolicy,
    assessment: CohortClaimAssessment,
    *,
    external_residual: str,
    receipt: BaselineTreatmentCohortReceipt | None = None,
) -> dict[str, Any]:
    """Project an assessment without adding trust inputs or execution authority."""

    if assessment.claim_eligible and receipt is None:
        raise ValueError("an eligible cohort projection MUST include its retained receipt")
    if receipt is not None and assessment.receipt_digest != receipt.receipt_digest:
        raise ValueError("cohort assessment and retained receipt digests MUST match")

    record: dict[str, Any] = {
        "claim_eligible": assessment.claim_eligible,
        "rejection_reasons": [reason.value for reason in assessment.rejection_reasons],
        "receipt_digest": assessment.receipt_digest,
        "minimum_sample_size": policy.minimum_sample_size,
        "artifact_origin": assessment.artifact_origin.value,
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "measurement_basis_kind": policy.measurement_basis_kind,
        "measurement_protocol_version": policy.measurement_protocol_version,
        "measurement_protocol_digest": policy.measurement_protocol_digest,
        "benchmark_scenario_set_version": policy.benchmark_scenario_set_version,
        "benchmark_scenario_set_digest": policy.benchmark_scenario_set_digest,
        "required_metric_ids": list(policy.required_metric_ids),
        "required_guard_ids": list(policy.required_guard_ids),
        "external_residual": None if assessment.claim_eligible else external_residual,
    }
    if receipt is not None:
        record["fdai_revision"] = receipt.fdai_revision
        record["evidence_cutoff"] = receipt.evidence_cutoff.isoformat()
        record["arms"] = {
            "baseline": _cohort_arm_record(receipt.baseline),
            "treatment": _cohort_arm_record(receipt.treatment),
        }
    return record


def publish_governed_baseline(summary: dict[str, Any]) -> None:
    """Publish only an eligible retained baseline as claim-bearing metrics."""

    cohort = summary["cohort_claim"]
    if not cohort["claim_eligible"]:
        summary["evidence"]["claim_eligible"] = False
        return

    baseline = cohort["arms"]["baseline"]
    metrics = {
        metric_id: baseline["metrics"][metric_id] for metric_id in cohort["required_metric_ids"]
    }
    guards = {guard_id: baseline["guards"][guard_id] for guard_id in cohort["required_guard_ids"]}
    if any(metric["confidence_level_basis_points"] != 9_500 for metric in metrics.values()):
        raise ValueError("eligible baseline metric intervals MUST use 95% confidence")
    summary["evidence"] = {
        "kind": "governed-cohort",
        "claim_eligible": True,
        "minimum_claim_sample_size": cohort["minimum_sample_size"],
        "sample_size": baseline["sample_count"],
        "receipt_digest": cohort["receipt_digest"],
        "fdai_revision": cohort["fdai_revision"],
        "evidence_cutoff": cohort["evidence_cutoff"],
    }
    summary["success_metrics"] = {
        metric_id: metric["absolute_value"] for metric_id, metric in metrics.items()
    }
    summary["confidence_intervals_95"] = {
        metric_id: {
            "sample_size": metric["sample_size"],
            "lower": metric["lower_bound"],
            "upper": metric["upper_bound"],
        }
        for metric_id, metric in metrics.items()
    }
    summary["guard_metrics_baseline"] = {
        guard_id: guard["observed_basis_points"] / 10_000 for guard_id, guard in guards.items()
    }
    summary["guard_metric_source"] = "governed baseline cohort"


def render_cohort_claim(cohort: dict[str, Any], *, korean: bool) -> list[str]:
    """Render one cohort claim section without exposing retained raw evidence."""

    if korean:
        lines = [
            "",
            "## 통제된 코호트 주장",
            "",
            f"- **주장 사용 가능**: `{str(cohort['claim_eligible']).lower()}`",
            f"- **산출물 출처**: `{cohort['artifact_origin']}`",
            f"- **신뢰 정책**: `{cohort['policy_id']}@{cohort['policy_version']}`",
            f"- **운영 프로토콜**: `{cohort['measurement_protocol_version']}`",
            f"- **운영 프로토콜 다이제스트**: `{cohort['measurement_protocol_digest']}`",
            f"- **별도 합성 벤치마크**: `{cohort['benchmark_scenario_set_version']}`",
            f"- **최소 표본 수**: {cohort['minimum_sample_size']}",
            "- **필수 성공 지표**: "
            + ", ".join(f"`{metric}`" for metric in cohort["required_metric_ids"]),
            "- **필수 영(0) 임계 가드**: "
            + ", ".join(f"`{guard}`" for guard in cohort["required_guard_ids"]),
            "- **거부 사유**: "
            + (", ".join(f"`{reason}`" for reason in cohort["rejection_reasons"]) or "없음"),
        ]
        if "arms" in cohort:
            lines += _render_retained_arm_evidence(cohort, korean=True)
        lines.append(f"- **외부 잔여 조건**: {cohort['external_residual'] or '없음'}.")
        return lines

    lines = [
        "",
        "## Governed Cohort Claim",
        "",
        f"- **Claim eligible**: `{str(cohort['claim_eligible']).lower()}`",
        f"- **Artifact origin**: `{cohort['artifact_origin']}`",
        f"- **Trusted policy**: `{cohort['policy_id']}@{cohort['policy_version']}`",
        f"- **Operational protocol**: `{cohort['measurement_protocol_version']}`",
        f"- **Operational protocol digest**: `{cohort['measurement_protocol_digest']}`",
        f"- **Separate synthetic benchmark**: `{cohort['benchmark_scenario_set_version']}`",
        f"- **Minimum sample size**: {cohort['minimum_sample_size']}",
        "- **Required success metrics**: "
        + ", ".join(f"`{metric}`" for metric in cohort["required_metric_ids"]),
        "- **Required zero-threshold guards**: "
        + ", ".join(f"`{guard}`" for guard in cohort["required_guard_ids"]),
        "- **Rejection reasons**: "
        + (", ".join(f"`{reason}`" for reason in cohort["rejection_reasons"]) or "none"),
    ]
    if "arms" in cohort:
        lines += _render_retained_arm_evidence(cohort, korean=False)
    lines.append(f"- **External residual**: {cohort['external_residual'] or 'none'}.")
    return lines


def _cohort_arm_record(arm: CohortArmReport) -> dict[str, Any]:
    return {
        "sample_count": arm.sample_count,
        "synthetic": arm.synthetic,
        "metrics_complete": arm.metrics_complete,
        "provenance_complete": arm.provenance_complete,
        "metrics": {
            metric.metric_id: {
                "absolute_value": metric.absolute_value,
                "sample_size": metric.sample_size,
                "confidence_level_basis_points": metric.confidence_level_basis_points,
                "lower_bound": metric.lower_bound,
                "upper_bound": metric.upper_bound,
            }
            for metric in arm.metrics
        },
        "guards": {
            guard.guard_id: {
                "observed_basis_points": guard.observed_basis_points,
                "maximum_basis_points": guard.maximum_basis_points,
                "sample_size": guard.sample_size,
                "breached": guard.breached,
            }
            for guard in arm.guards
        },
        "report_digest": arm.report_digest,
        "provenance_digest": arm.provenance_digest,
        "evidence_receipt_digest": arm.evidence_receipt.receipt_digest,
    }


def _render_retained_arm_evidence(cohort: dict[str, Any], *, korean: bool) -> list[str]:
    baseline = cohort["arms"]["baseline"]
    treatment = cohort["arms"]["treatment"]
    if korean:
        return [
            f"- **증적 다이제스트**: `{cohort['receipt_digest']}`",
            f"- **FDAI 리비전**: `{cohort['fdai_revision']}`",
            f"- **근거 기준 시점**: {cohort['evidence_cutoff']}",
            f"- **기준선 표본**: {baseline['sample_count']}",
            f"- **처리군 표본**: {treatment['sample_count']}",
            f"- **기준선 출처 다이제스트**: `{baseline['provenance_digest']}`",
            f"- **처리군 출처 다이제스트**: `{treatment['provenance_digest']}`",
        ]
    return [
        f"- **Receipt digest**: `{cohort['receipt_digest']}`",
        f"- **FDAI revision**: `{cohort['fdai_revision']}`",
        f"- **Evidence cutoff**: {cohort['evidence_cutoff']}",
        f"- **Baseline samples**: {baseline['sample_count']}",
        f"- **Treatment samples**: {treatment['sample_count']}",
        f"- **Baseline provenance digest**: `{baseline['provenance_digest']}`",
        f"- **Treatment provenance digest**: `{treatment['provenance_digest']}`",
    ]


__all__ = ["cohort_claim_record", "publish_governed_baseline", "render_cohort_claim"]
