from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from fdai.agents._framework.adapters import AuditChainError, InMemoryAuditChain
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents._framework.provider_adapters import StateStoreAuditChainAdapter
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.odin import Odin
from fdai.agents.saga import Saga
from fdai.agents.var import Var
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon())


def _action_run(**overrides: object) -> dict[str, object]:
    correlation_id = str(overrides.get("correlation_id") or "corr-action")
    payload: dict[str, object] = {
        "producer_principal": "Thor",
        "correlation_id": correlation_id,
        "idempotency_key": f"action-run:{correlation_id}",
        "action_type": "ops.unknown-action",
        "resource_id": "resource-1",
        "state": "hil_pending",
        "quorum_required": 1,
    }
    payload.update(overrides)
    return payload


async def _drain_bridge(bridge: EventBusBridge, *, done) -> None:  # type: ignore[no-untyped-def]
    run_task = asyncio.create_task(bridge.run())
    for _ in range(40):
        await asyncio.sleep(0)
        if done():
            break
    await bridge.stop()
    run_task.cancel()
    try:
        await run_task
    except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
        pass


def test_live_bridge_rejects_owner_stamped_malformed_verdict_before_handler() -> None:
    provider = InMemoryEventBus()
    bridge = EventBusBridge(
        provider=provider,
        registry=load_pantheon(),
        payload_validator=lambda topic, payload: PantheonRuntime.build(
            provider=InMemoryEventBus(),
            raw_event_topic="runtime.raw",
        ).bridge.payload_validator(topic, payload),
    )
    delivered: list[dict[str, object]] = []

    async def handler(_topic: str, payload: dict[str, object]) -> None:
        delivered.append(dict(payload))

    bridge.subscribe("object.verdict", "Thor", handler)

    async def _run() -> list[dict[str, object]]:
        await provider.publish(
            "object.verdict",
            "corr-bridge",
            {
                "producer_principal": "Forseti",
                "correlation_id": "corr-bridge",
                "idempotency_key": "verdict:corr-bridge",
                "risk_verdict": "auto",
                "resolved_autonomy_ceiling": "enforce_auto",
                "action_type": "ops.mutate",
            },
        )
        await _drain_bridge(bridge, done=lambda: bridge.metrics.dead_lettered > 0)
        return [
            dict(item.payload)
            async for item in provider.subscribe("object.verdict.dlq", "assert-dlq")
        ]

    dlq = asyncio.run(_run())

    assert delivered == []
    assert bridge.metrics.dead_lettered == 1
    assert dlq[0]["payload"]["correlation_id"] == "corr-bridge"


def test_runtime_default_payload_validator_rejects_malformed_authority_payloads() -> None:
    runtime = PantheonRuntime.build(provider=InMemoryEventBus(), raw_event_topic="runtime.raw")

    with pytest.raises(ValueError, match="verdict payload"):
        asyncio.run(
            runtime.bridge.publish(
                "Forseti",
                "object.verdict",
                {"correlation_id": "corr-v", "idempotency_key": "verdict:corr-v"},
            )
        )
    with pytest.raises(ValueError, match="state"):
        asyncio.run(
            runtime.bridge.publish(
                "Thor",
                "object.action-run",
                {
                    "correlation_id": "corr-a",
                    "idempotency_key": "action-run:corr-a",
                    "resource_id": "resource-1",
                },
            )
        )
    with pytest.raises(ValueError, match="approval"):
        asyncio.run(
            runtime.bridge.publish(
                "Var",
                "object.approval",
                {"correlation_id": "corr-p", "idempotency_key": "approval:corr-p"},
            )
        )


def test_var_rejects_non_thor_action_run_before_ticket() -> None:
    var = Var()

    asyncio.run(
        var.on_typed_message(
            "object.action-run",
            _action_run(producer_principal="Mallory", correlation_id="corr-var-owner"),
        )
    )

    assert var.pending_tickets() == ()
    assert var.behavior_snapshot()["typed_message:rejected_owner"] == 1


def test_var_rederives_unknown_action_quorum_and_rejects_oversized_params() -> None:
    var = Var()
    asyncio.run(var.on_typed_message("object.action-run", _action_run(correlation_id="corr-q")))
    ticket = var.pending_tickets()[0]
    assert ticket.quorum_required == 2

    oversized = {"blob": "x" * 20_000}
    asyncio.run(
        var.on_typed_message(
            "object.action-run",
            _action_run(correlation_id="corr-big", params=oversized),
        )
    )
    assert {item.correlation_id for item in var.pending_tickets()} == {"corr-q"}
    assert var.behavior_snapshot()["ticket_invalid_params"] == 1


def test_odin_authenticates_and_bounds_arbitration_requests() -> None:
    bus = _bus()
    odin = Odin(bus=bus)

    asyncio.run(
        odin.on_typed_message(
            "object.arbitration-request",
            {
                "producer_principal": "Mallory",
                "correlation_id": "corr-odin-owner",
                "idempotency_key": "arb:corr-odin-owner",
                "domains_in_conflict": ["cost", "capacity"],
            },
        )
    )
    assert bus.messages_on("object.arbitration-decision") == []

    asyncio.run(
        odin.on_typed_message(
            "object.arbitration-request",
            {
                "producer_principal": "Forseti",
                "correlation_id": "corr-odin-big",
                "idempotency_key": "arb:corr-odin-big",
                "domains_in_conflict": [f"domain-{i}" for i in range(100)],
            },
        )
    )
    assert bus.messages_on("object.arbitration-decision") == []
    assert odin.behavior_snapshot()["arbitration:invalid_domains"] == 1


@pytest.mark.parametrize(
    ("topic", "payload"),
    [
        (
            "object.verdict",
            {
                "kind": "document_ingestion",
                "correlation_id": "corr-doc-verdict",
                "idempotency_key": "verdict:corr-doc-verdict",
            },
        ),
        (
            "object.approval",
            {
                "kind": "document_ingestion",
                "correlation_id": "corr-doc-approval",
                "idempotency_key": "approval:corr-doc-approval",
            },
        ),
        (
            "object.action-run",
            {
                "correlation_id": "corr-action-outcome",
                "idempotency_key": "action-run:corr-action-outcome",
                "state": "succeeded",
                "action_type": "ops.restart-service",
                "resource_id": "resource-1",
            },
        ),
        (
            "object.forecast-outcome",
            {
                "correlation_id": "corr-forecast",
                "idempotency_key": "forecast:corr-forecast",
                "outcome_id": "forecast-outcome-1",
            },
        ),
        (
            "object.rule",
            {
                "kind": "catalog_review_outcome",
                "correlation_id": "corr-rule",
                "idempotency_key": "rule:corr-rule",
            },
        ),
    ],
)
def test_saga_rejects_wrong_owner_before_append_or_republish(
    topic: str, payload: dict[str, object]
) -> None:
    bus = _bus()
    saga = Saga()
    saga.bind_bus(bus)
    payload = {"producer_principal": "Mallory", **payload}

    asyncio.run(saga.on_typed_message(topic, payload))

    assert saga.audit_chain.entries == []
    assert bus.messages_on("object.audit-entry") == []
    assert saga.behavior_snapshot()["typed_message:rejected_owner"] == 1


def test_saga_requires_bragi_handoff_owner_before_issue_materialization() -> None:
    saga = Saga()
    payload = {
        "producer_principal": "Mallory",
        "correlation_id": "corr-handoff-owner",
        "idempotency_key": "handoff:corr-handoff-owner",
        "escalation_id": "esc-owner",
        "emitting_agent": "Bragi",
        "intent_category": "handoff",
        "resource_type": "service",
        "normalized_selector": "sha256:abc",
        "failure_reason_code": "needs-human",
    }

    asyncio.run(saga.on_typed_message("object.handoff-escalation", payload))

    assert saga.github.issues == {}
    assert saga.audit_chain.entries == []


def test_saga_handoff_issue_context_is_allowlisted_and_bounded() -> None:
    saga = Saga()

    result = asyncio.run(
        saga.escalate_to_github_issue(
            fingerprint="f" * 64,
            emitting_agent="Bragi",
            intent_category="handoff",
            failure_reason_code="needs-human",
            correlation_id="corr-context",
            context={
                "trace_ref": "trace://example",
                "payload_digest": "sha256:" + "a" * 64,
                "token": "secret-token-value",
            },
        )
    )

    issue = saga.github.issues["f" * 64]
    assert result["issue_number"] == issue.number
    assert "trace_ref" in issue.body
    assert "payload_digest" in issue.body
    assert "secret-token-value" not in issue.body
    assert "token" not in issue.body


def test_state_store_audit_chain_detects_entry_tampering() -> None:
    adapter = StateStoreAuditChainAdapter(InMemoryStateStore())
    entry = asyncio.run(
        adapter.append(
            principal="Saga",
            topic="object.audit-entry",
            correlation_id="corr-audit-tamper",
            payload={
                "correlation_id": "corr-audit-tamper",
                "idempotency_key": "audit:corr-audit-tamper",
            },
        )
    )
    adapter.entries[0] = replace(entry, principal="Mallory")

    with pytest.raises(AuditChainError, match="entry hash mismatch"):
        adapter.verify()


def test_inmemory_audit_chain_detects_tail_truncation() -> None:
    chain = InMemoryAuditChain()
    chain.append(
        principal="Saga",
        topic="object.audit-entry",
        correlation_id="corr-audit-one",
        payload={"correlation_id": "corr-audit-one", "idempotency_key": "audit:corr-audit-one"},
    )
    chain.append(
        principal="Saga",
        topic="object.audit-entry",
        correlation_id="corr-audit-two",
        payload={"correlation_id": "corr-audit-two", "idempotency_key": "audit:corr-audit-two"},
    )
    chain.entries.pop()

    with pytest.raises(AuditChainError, match="chain length mismatch"):
        chain.verify()
