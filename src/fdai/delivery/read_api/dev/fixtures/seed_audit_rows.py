"""Synthetic audit rows for the local read API fixture."""

from __future__ import annotations

_SeedRow = tuple[str, str, str, str, str, str, str, str, int, dict[str, str], dict[str, str]]

SEED_AUDIT_ROWS: tuple[_SeedRow, ...] = (
    (
        "Huginn",
        "t0",
        "event.ingest",
        "normalized",
        "10:00:00",
        "corr-a",
        "Normalized 1 Activity Log event into a finding",
        "Consumed 1 Azure Activity Log record for vm-1, deduplicated it against "
        "the 5-minute correlation window, and emitted normalized finding "
        "fnd-0001 (category=security) onto the event bus for the trust router.",
        180,
        {
            "source": "azure.activity_log",
            "events_in": "1",
            "resource": "vm-1 (compute.vm)",
            "region": "eastus",
        },
        {
            "finding_id": "fnd-0001",
            "category": "security",
            "severity": "medium",
            "deduplicated": "0",
        },
    ),
    (
        "Heimdall",
        "t0",
        "anomaly.detect",
        "within_threshold",
        "10:02:00",
        "corr-a",
        "Metric anomaly check: no deviation over threshold",
        "Scored the vm-1 metric window against the learned baseline; the "
        "z-score (0.7) stayed under the 3.0 alert threshold, so no anomaly "
        "finding was raised - detection ran in shadow and only logged.",
        220,
        {
            "finding_id": "fnd-0001",
            "metric": "cpu_credits_remaining",
            "window": "5m",
            "baseline": "learned-v3",
        },
        {"z_score": "0.7", "threshold": "3.0", "anomaly": "false"},
    ),
    (
        "Forseti",
        "t0",
        "verdict.issue",
        "auto",
        "10:05:00",
        "corr-a",
        "Deterministic rule matched; verdict=auto",
        "Matched finding fnd-0001 to rule azure-encryption-at-rest-001 (exact, "
        "confidence 1.0). Single-rule match, low blast radius -> verdict=auto. "
        "No LLM tier was invoked; grounded on the rule citation only.",
        340,
        {
            "finding_id": "fnd-0001",
            "rule": "azure-encryption-at-rest-001",
            "match": "exact",
            "confidence": "1.0",
        },
        {"verdict": "auto", "risk": "low", "citations": "1"},
    ),
    (
        "Thor",
        "t0",
        "enable-encryption",
        "shadow_pr_opened",
        "10:06:00",
        "corr-a",
        "Opened remediation PR to enable encryption at rest",
        "Rendered the Terraform diff to enable encryption at rest on vm-1's "
        "OS disk, ran what-if (no destructive change), and opened remediation "
        "PR #482 in shadow mode. The PR is the audit + rollback surface; "
        "nothing was applied to the live resource.",
        1200,
        {
            "verdict": "auto",
            "resource": "vm-1",
            "change": "encryption_at_rest=on",
            "delivery": "pr_native",
        },
        {
            "pr": "#482",
            "what_if": "no_destructive_change",
            "mode": "shadow",
            "applied": "false",
        },
    ),
    (
        "Saga",
        "t0",
        "audit.record",
        "recorded",
        "10:06:30",
        "corr-a",
        "Appended terminal decision to the audit log",
        "Sealed the corr-a chain: appended the terminal decision as an "
        "append-only, hash-linked audit row (entry_hash over the prior hash) "
        "so the incident is deterministically replayable.",
        90,
        {"correlation": "corr-a", "terminal": "shadow_pr_opened", "steps": "4"},
        {"audit_seq": "recorded", "hash_linked": "true"},
    ),
    (
        "Njord",
        "t0",
        "cost.anomaly",
        "finding_raised",
        "10:12:00",
        "corr-b",
        "Idle public endpoint flagged for cost review",
        "A daily cost probe found public endpoint pe-9 billing with near-zero "
        "traffic for 14 days. Raised cost finding fnd-0002 (est. saving "
        "$38/mo) for the trust router to judge.",
        260,
        {
            "probe": "cost.idle_endpoint",
            "resource": "pe-9 (network.public_ip)",
            "idle_days": "14",
            "traffic": "~0",
        },
        {"finding_id": "fnd-0002", "est_saving_usd_month": "38", "category": "cost"},
    ),
    (
        "Forseti",
        "t0",
        "verdict.issue",
        "auto",
        "10:13:00",
        "corr-b",
        "Cost rule matched; verdict=auto (shadow)",
        "Matched fnd-0002 to rule cost-idle-public-endpoint-004 (exact). Low "
        "blast radius, reversible -> verdict=auto, but the action ships in "
        "shadow until the promotion gate clears.",
        300,
        {
            "finding_id": "fnd-0002",
            "rule": "cost-idle-public-endpoint-004",
            "match": "exact",
            "confidence": "1.0",
        },
        {"verdict": "auto", "risk": "low", "default_mode": "shadow"},
    ),
    (
        "Thor",
        "t0",
        "close-idle-endpoint",
        "shadow_pr_opened",
        "10:14:00",
        "corr-b",
        "Opened remediation PR to close idle endpoint",
        "Rendered the Terraform diff to deallocate public endpoint pe-9, ran "
        "what-if (reversible via pr_revert), and opened remediation PR #483 in "
        "shadow mode. Rollback contract: pr_revert.",
        1100,
        {
            "verdict": "auto",
            "resource": "pe-9",
            "change": "deallocate",
            "delivery": "pr_native",
        },
        {"pr": "#483", "rollback": "pr_revert", "mode": "shadow", "applied": "false"},
    ),
    (
        "Freyr",
        "t0",
        "capacity.forecast",
        "forecast_ok",
        "10:20:00",
        "corr-c",
        "7-day capacity forecast within headroom",
        "Projected 7-day capacity for the aks-prod node pool from the trailing "
        "28-day trend. Peak projected utilization 62% stays under the 80% "
        "headroom target, so no scale action was proposed.",
        500,
        {"scope": "aks-prod/nodepool-1", "horizon": "7d", "trend_window": "28d"},
        {"projected_peak": "62%", "headroom_target": "80%", "action": "none"},
    ),
    (
        "Muninn",
        "t1",
        "similarity.recall",
        "matched_prior",
        "10:42:00",
        "corr-d",
        "Recalled a resolved incident with 0.91 similarity",
        "Embedded the new finding and searched the incident memory (pgvector). "
        "Nearest resolved incident inc-2041 scored 0.91 cosine, over the 0.85 "
        "reuse threshold - handed the match to Norns for action reuse (T1).",
        150,
        {
            "finding_id": "fnd-0003",
            "index": "incident_memory",
            "metric": "cosine",
            "threshold": "0.85",
        },
        {"match": "inc-2041", "score": "0.91", "tier": "T1"},
    ),
    (
        "Norns",
        "t1",
        "reuse-learned-action",
        "shadow_pr_opened",
        "10:43:00",
        "corr-d",
        "Reused a learned action from the matched incident",
        "Adapted the learned remediation from inc-2041 to the current resource, "
        "re-validated it against policy-as-code (pass), and opened PR #484 in "
        "shadow. Reuse avoided a T2 model call.",
        800,
        {"source_incident": "inc-2041", "score": "0.91", "verifier": "policy_as_code"},
        {"pr": "#484", "verifier": "pass", "mode": "shadow", "llm_calls_saved": "1"},
    ),
    (
        "Odin",
        "t2",
        "arbitrate.cross-vertical",
        "resolved",
        "10:54:00",
        "corr-e",
        "Arbitrated resilience-vs-cost conflict before verdict",
        "Two verticals proposed opposing actions on aks-prod (resilience: scale "
        "up; cost: scale down). Odin arbitrated using the cross-vertical policy "
        "and resolved in favour of resilience during the change-freeze window.",
        640,
        {"conflict": "resilience_vs_cost", "resource": "aks-prod", "proposals": "2"},
        {"winner": "resilience", "reason": "change_freeze_window", "handoff": "Forseti"},
    ),
    (
        "Forseti",
        "t2",
        "root-cause-reasoning",
        "escalated_hil",
        "10:55:00",
        "corr-e",
        "Novel case: mixed-model cross-check disagreed; escalated to HIL",
        "Novel case (no rule, similarity below threshold) routed to T2. The "
        "two cross-check models disagreed on root cause (model-a: throttling; "
        "model-b: node pressure), so the quality gate refused to auto-resolve "
        "and escalated to human-in-the-loop.",
        2100,
        {"tier": "T2", "models": "2", "grounding": "required"},
        {
            "agreement": "false",
            "model_a": "throttling",
            "model_b": "node_pressure",
            "decision": "escalate_hil",
        },
    ),
    (
        "Var",
        "t2",
        "hil.await",
        "awaiting_approval",
        "10:55:30",
        "corr-e",
        "High-risk action queued for a human approver",
        "Registered the escalated action in the HIL queue for a distinct human "
        "approver (no self-approval). It stays parked - no execution - until an "
        "operator approves or the request times out to a no-op.",
        70,
        {
            "action": "remediate.restrict-network-access",
            "risk": "high",
            "approver_role": "sre-oncall",
        },
        {"queue": "hil", "state": "awaiting_approval", "self_approval": "blocked"},
    ),
    (
        "Njord",
        "t0",
        "cost-anomaly.detect",
        "flagged",
        "11:00:00",
        "corr-f",
        "Cost anomaly: sustained under-utilization on vmss-web",
        "Sampled 14 days of utilization for vmss-web: CPU held under 15 percent "
        "with ample headroom. Flagged it as a right-size candidate and handed "
        "the finding to Forseti for a verdict.",
        210,
        {"resource": "vmss-web", "window": "14d", "avg_cpu": "12%"},
        {"candidate": "right_size", "monthly_cost": "312"},
    ),
    (
        "Thor",
        "t0",
        "right_size",
        "shadow_pr_opened",
        "11:01:00",
        "corr-f",
        "Opened remediation PR to right-size an over-provisioned VMSS",
        "Rendered the Terraform diff to move vmss-web from Standard_D4s_v5 to "
        "Standard_D2s_v5 (utilization headroom preserved), ran what-if (no data "
        "loss), and opened remediation PR #486 in shadow. Nothing was applied "
        "to the live resource.",
        1100,
        {"resource": "vmss-web", "from": "D4s_v5", "to": "D2s_v5", "delivery": "pr_native"},
        {"pr": "#486", "mode": "shadow", "estimated_savings": "128.0"},
    ),
    (
        "Thor",
        "t0",
        "shutdown",
        "shadow_pr_opened",
        "11:02:00",
        "corr-g",
        "Opened remediation PR to deallocate an idle dev VM",
        "Detected dev-vm-07 stopped-but-allocated for 9 days; rendered the diff "
        "to deallocate it, ran what-if (reversible), and opened remediation PR "
        "#487 in shadow. Reversible, resource-scoped, low cost.",
        900,
        {"resource": "dev-vm-07", "state": "stopped_allocated", "idle_days": "9"},
        {"pr": "#487", "mode": "shadow", "estimated_savings": "45.5"},
    ),
    (
        "Thor",
        "t0",
        "enable-zone-redundancy",
        "shadow_pr_opened",
        "11:10:00",
        "corr-h",
        "Opened remediation PR to enable zone redundancy on prod PostgreSQL",
        "Detected prod-pg-01 running single-zone; rendered the Terraform diff to "
        "enable zone redundancy, ran what-if (no downtime), and opened "
        "remediation PR #490 in shadow.",
        1000,
        {"resource": "prod-pg-01", "change": "zone_redundant=true", "delivery": "pr_native"},
        {"pr": "#490", "mode": "shadow"},
    ),
    (
        "Vidar",
        "t0",
        "dr-failover-drill",
        "verified",
        "11:11:00",
        "corr-i",
        "Ran a shadow DR failover drill and verified RTO",
        "Executed a shadow disaster-recovery failover drill for the prod region "
        "pair; measured recovery time under the RTO target and logged the "
        "result. No production traffic was moved.",
        1400,
        {"region_pair": "krc/krs", "rto_target_s": "300"},
        {"rto_measured_s": "228", "within_target": "true"},
    ),
    (
        "Var",
        "t2",
        "restore-from-backup",
        "awaiting_approval",
        "11:12:00",
        "corr-j",
        "High-risk restore queued for a human approver",
        "A point-in-time restore of prod-pg-01 was proposed after a suspected "
        "logical corruption; it is data-plane and irreversible, so it parks in "
        "the HIL queue for a human approver rather than auto-executing.",
        80,
        {"resource": "prod-pg-01", "risk": "high", "data_plane": "true"},
        {"queue": "hil", "state": "awaiting_approval"},
    ),
)

__all__ = ["SEED_AUDIT_ROWS"]
