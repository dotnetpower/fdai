"""Synthetic local audit, HIL, and metering fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.delivery.read_api.dev.fixtures.seed_audit_rows import SEED_AUDIT_ROWS
from fdai.delivery.read_api.dev.fixtures.seed_conversations import (
    CONVERSATIONS as _CONVERSATIONS,
)
from fdai.delivery.read_api.dev.fixtures.seed_measurements import (
    synthetic_llm_invocations,
    synthetic_verdicts,
)
from fdai.delivery.read_api.read_model import HilQueueItem, InMemoryConsoleReadModel


def _synthetic_verdicts() -> list[Any]:
    return synthetic_verdicts()


def _synthetic_llm_invocations() -> tuple[Any, ...]:
    return synthetic_llm_invocations()


# Agent-to-agent conversational-port exchanges (§6.2), keyed by the 1-based
# seed-row index. These are the natural-language turns an agent has with other
# agents while doing the typed work on that row (e.g. Odin arbitrating asks the
# domain agents in NL). Each turn is {from, to, text}; English + audit-safe.
def _seed(read_model: InMemoryConsoleReadModel) -> None:
    """Seed audit entries (with trust tiers) + one pending HIL so the SPA renders data.

    Each entry is attributed to the pantheon agent that produced it
    (``actor`` == ``producer_principal``) so the agent-activity waterfall
    can reconstruct "which agent did what, when, and how". Beyond the
    terminal decision, every row carries a lifecycle trace - when the
    upstream event was emitted (``event_ts``), when this agent received it
    (``received_at``), when work began (``started_at``) and finished
    (``finished_at`` == ``recorded_at``), plus ``duration_ms`` / ``queue_ms``
    and structured ``inputs`` / ``outputs`` / ``detail`` - so the console
    detail pane can show the full send -> receive -> work -> record span.
    The tier / outcome / mode split stays realistic (T0-heavy) so the KPI
    dashboard keeps rendering a plausible distribution from the same rows.
    """
    base_day = "2026-07-06T"
    # transit (event_ts -> received) and scheduling (received -> started) delays.
    transit_ms = 40
    queue_ms = 80
    prev_finish_by_corr: dict[str, datetime] = {}
    for i, row in enumerate(SEED_AUDIT_ROWS, start=1):
        (
            agent,
            tier,
            action_kind,
            outcome,
            hhmmss,
            correlation,
            summary,
            detail,
            work_ms,
            inputs,
            outputs,
        ) = row
        finished = datetime.fromisoformat(f"{base_day}{hhmmss}+00:00")
        started = finished - timedelta(milliseconds=work_ms)
        received = started - timedelta(milliseconds=queue_ms)
        # event_ts = when the upstream producer emitted what this agent consumed:
        # the previous agent's finish in the same incident, else shortly before
        # this agent received it (the source signal arriving).
        sent = prev_finish_by_corr.get(correlation, received - timedelta(milliseconds=transit_ms))
        prev_finish_by_corr[correlation] = finished
        entry: dict[str, Any] = {
            "event_id": f"00000000-0000-0000-0000-{i:012d}",
            "correlation_id": correlation,
            "actor": agent,
            "producer_principal": agent,
            "action_kind": action_kind,
            "mode": "shadow",
            "outcome": outcome,
            "tier": tier,
            "summary": summary,
            "detail": detail,
            "event_ts": sent.isoformat(),
            "received_at": received.isoformat(),
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_ms": work_ms,
            "queue_ms": queue_ms,
            "inputs": inputs,
            "outputs": outputs,
            "conversation": list(_CONVERSATIONS.get(i, ())),
            "recorded_at": finished.isoformat(),
        }
        # The FinOps panel sums a top-level ``estimated_savings``; a cost row
        # carries it in ``outputs`` (all str), so promote it to the entry root.
        _savings = outputs.get("estimated_savings")
        if _savings is not None:
            entry["estimated_savings"] = float(_savings)
        read_model.record_audit_entry(entry)
    hil_requested_at = datetime.now(tz=UTC)
    read_model.record_hil_pending(
        HilQueueItem(
            idempotency_key="hil-dev-0001",
            event_id="00000000-0000-0000-0000-000000000010",
            action_kind="remediate.restrict-network-access",
            reason="blast-radius exceeds executor cap",
            requested_at=hil_requested_at.isoformat(),
            correlation_id="corr-dev-0001",
            approval_id="approval-dev-0001",
            action_id="action-dev-0001",
            target_resource_ref="web-api",
            mode="shadow",
            stop_condition="health probe fails or approved scope changes",
            rollback_kind="pr_revert",
            rollback_reference="remediation-pr/example-network-lockdown",
            blast_radius_scope="resource_group",
            blast_radius_count=12,
            blast_radius_rate_per_minute=2,
            blast_radius_summary="12 resources in one resource group; 2/min cap",
            reasons=(
                "blast-radius exceeds executor cap",
                "distinct human approval is required before enforce mode",
            ),
            citing_rule_ids=("network.nsg.no-inbound-any-ssh",),
            ttl_expires_at=(hil_requested_at + timedelta(minutes=30)).isoformat(),
        )
    )
    _seed_trace(read_model, "corr-dev-0001")


def _seed_trace(read_model: InMemoryConsoleReadModel, correlation: str) -> None:
    """Seed a full pipeline trace under ``correlation`` so the trace / bitemporal
    / what-if routes have a rich sample record to render."""
    base = datetime(2026, 7, 6, 10, 10, 0, tzinfo=UTC)
    steps: tuple[dict[str, Any], ...] = (
        {
            "pipeline_stage": "event_ingest",
            "action_kind": "event.received",
            "payload": {
                "resource": {
                    "resource_id": "vm-1",
                    "type": "compute.vm",
                    "props": {"tier": "S1", "region": "eastus"},
                }
            },
            "state": {"tier": "S1"},
            "effective_at": base.isoformat(),
        },
        {
            "pipeline_stage": "L1_evaluate",
            "action_kind": "trust_router.route",
            "decision": "match",
            "reason": "public_access_enabled",
        },
        {
            "pipeline_stage": "risk_gate",
            "action_kind": "risk_gate.evaluate",
            "decision": "escalate_hil",
            "reason": "blast-radius exceeds executor cap",
            "state": {"tier": "S2", "region": "eastus"},
            "effective_at": (base + timedelta(minutes=5)).isoformat(),
        },
        {
            "pipeline_stage": "escalate",
            "action_kind": "restrict-network-access",
            "decision": "hil_pending",
            "reason": "awaiting human approval",
            "mode": "shadow",
        },
    )
    for offset, entry in enumerate(steps):
        entry_copy = dict(entry)
        entry_copy["correlation_id"] = correlation
        entry_copy["recorded_at"] = (base + timedelta(seconds=offset)).isoformat()
        read_model.record_audit_entry(entry_copy)
