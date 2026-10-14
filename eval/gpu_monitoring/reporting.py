"""Evidence-backed advisory reports; neither diagnosis nor remediation authority."""

from __future__ import annotations

from eval.gpu_monitoring.models import Analysis

_GUIDANCE = {
    "new_xid_code": (
        "A new driver diagnostic code was observed; the faulty component is not established.",
        "Correlate driver logs, workload errors and node health; request a reviewed recovery plan.",
    ),
    "new_ecc_error": (
        "An uncorrectable ECC counter increased; hardware health needs independent confirmation.",
        "Collect diagnostics and checkpoint status before proposing an approved node drain.",
    ),
    "observed_cuda_oom": (
        "A workload OOM counter increased; batch size or competing allocations may be involved.",
        "Correlate CUDA logs and allocations; propose a reversible batch/concurrency adjustment.",
    ),
    "observed_thermal_throttle": (
        "Explicit throttle evidence exists; cooling or sustained load may contribute.",
        "Correlate clock and power telemetry with host health; request operator review.",
    ),
    "high_temperature": (
        "Temperature crossed the example threshold; thermal throttling is not proven.",
        "Compare the installed GPU's thermal specification and clock/throttle telemetry.",
    ),
    "memory_pressure": (
        "Framebuffer occupancy is high; neither a leak nor CUDA OOM is proven.",
        "Correlate batch size, KV cache and process allocations; propose a bounded change.",
    ),
    "sustained_saturation_backlog": (
        "Sustained compute utilization and rising backlog suggest capacity pressure.",
        "Check latency SLO and quota before proposing scaling or concurrency changes.",
    ),
    "saturation_missing_queue_evidence": (
        "High compute utilization alone does not establish an incident or capacity shortage.",
        "Collect workload queue depth and latency before drawing a capacity conclusion.",
    ),
    "allocated_idle_window": (
        "An allocated GPU is idle in the observed window; waste or a hang is not proven.",
        "Check schedules, CPU/data-loading bottlenecks and ownership before a cost recommendation.",
    ),
}
_FOLLOWUP_FIELDS = {
    "new_xid_code": ("xid_code",),
    "new_ecc_error": ("ecc_uncorrectable_total",),
    "observed_cuda_oom": ("cuda_oom_total",),
    "observed_thermal_throttle": ("thermal_throttled",),
    "high_temperature": ("temperature_c",),
    "memory_pressure": ("memory_used_mib", "memory_total_mib"),
    "sustained_saturation_backlog": ("utilization_pct", "queue_depth"),
    "saturation_missing_queue_evidence": ("utilization_pct", "queue_depth"),
    "allocated_idle_window": ("utilization_pct", "allocated"),
}


def build_report(result: Analysis) -> dict[str, object]:
    """Return a local alert-shaped report with explicit evidence and capability limits."""
    findings: list[dict[str, object]] = []
    for event in result.events:
        kind = event.payload["finding_kind"]
        hypothesis, recommendation = _GUIDANCE[kind]
        findings.append(
            {
                "event_id": str(event.event_id),
                "idempotency_key": event.idempotency_key,
                "signal": event.payload["signal"],
                "finding_kind": kind,
                "severity": event.payload["severity"],
                "hypothesis": hypothesis,
                "recommendation": recommendation,
            }
        )
    return {
        "schema_version": "1.0.0",
        "evidence_origin": "synthetic_replay",
        "mode": "shadow",
        "status": result.status,
        "reason": result.reason,
        "root_cause_status": "hypothesis_only" if findings else "not_established",
        "execution_status": "not_executed",
        "external_effect_verified": False,
        "evidence_digest": result.evidence_digest,
        "policy_digest": result.policy_digest,
        "sample_count": len(result.samples),
        "latest_observation": (
            result.samples[-1].model_dump(mode="json") if result.samples else None
        ),
        "missing_optional_metrics": [
            field
            for field in (
                "allocated",
                "queue_depth",
                "xid_code",
                "ecc_uncorrectable_total",
                "cuda_oom_total",
                "thermal_throttled",
            )
            if not result.samples
            or any(getattr(sample, field) is None for sample in result.samples)
        ],
        "findings": findings,
        "required_execution_gates": [
            "registered_action_and_promotion",
            "risk_and_current_human_authorization",
            "stop_condition",
            "tested_rollback",
            "blast_radius_limit",
            "successful_dry_run",
            "logical_target_lock",
            "stable_idempotency_key",
            "two_phase_audit",
            "independent_effect_observation",
        ],
    }


def verify_followup(before: Analysis, after: Analysis) -> dict[str, object]:
    """Compare non-overlapping replay windows, never claim real remediation success."""
    status = "unverified"
    if (
        before.status == "finding"
        and after.status != "insufficient_evidence"
        and before.samples
        and after.samples
        and before.samples[-1].identity == after.samples[-1].identity
        and after.samples[0].observed_at > before.samples[-1].observed_at
        and all(
            getattr(sample, field) is not None
            for event in before.events
            for field in _FOLLOWUP_FIELDS[event.payload["finding_kind"]]
            for sample in after.samples
        )
    ):
        status = "recovered_in_replay" if after.status == "healthy" else "still_failing"
    return {
        "evidence_origin": "synthetic_replay",
        "verification_status": status,
        "execution_status": "not_executed",
        "external_effect_verified": False,
        "before_evidence_digest": before.evidence_digest,
        "after_evidence_digest": after.evidence_digest,
        "after_report": build_report(after),
    }
