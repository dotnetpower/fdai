from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.bragi import Bragi
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.agents.var import Var
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RULE_GENERATION_BUILD_REQUEST_TOPIC,
)


def _hil_payload(correlation_id: str = "corr-var") -> dict[str, object]:
    return {
        "producer_principal": "Thor",
        "correlation_id": correlation_id,
        "idempotency_key": f"{correlation_id}:hil",
        "action_type": "ops.restart-service",
        "resource_id": "resource-1",
        "state": "hil_pending",
    }


def _semantics() -> ActionSemanticsCatalog:
    return ActionSemanticsCatalog(
        irreversible_by_id={"ops.restart-service": False},
        rollback_by_id={},
    )


async def test_var_records_ignored_invalid_duplicate_and_missing_authority_paths() -> None:
    var = Var(action_semantics=_semantics())

    await var.on_typed_message(
        "object.event",
        {
            "producer_principal": "Huginn",
            "correlation_id": "event-ignored",
            "idempotency_key": "event-ignored",
            "event_type": "unrelated",
        },
    )
    for state in ("verdicted", "approved", "succeeded"):
        await var.on_typed_message(
            "object.action-run",
            {**_hil_payload(f"corr-{state}"), "state": state},
        )
    await var.on_typed_message(
        "object.action-run",
        {
            "producer_principal": "Thor",
            "idempotency_key": "missing-correlation",
            "resource_id": "resource-missing",
            "state": "hil_pending",
        },
    )
    await var.on_typed_message("object.action-run", _hil_payload("corr-dup"))
    await var.on_typed_message("object.action-run", _hil_payload("corr-dup"))
    decision = await var.decide(
        "missing-ticket",
        approver="approver@example.com",
        decision="approve",
    )
    shadow = await var.decide_shadow_review(
        "missing-shadow",
        reviewer="reviewer@example.com",
        agreed=True,
    )

    behavior = var.behavior_snapshot()
    assert behavior["typed_message:ignored"] == 1
    assert behavior["action_run:ignored_state:verdicted"] == 1
    assert behavior["action_run:ignored_state:approved"] == 1
    assert behavior["action_run:ignored_state:succeeded"] == 1
    assert behavior["ticket_invalid_correlation"] == 1
    assert behavior["ticket_duplicate"] == 1
    assert behavior["decision:missing_ticket"] == 1
    assert decision is not None and decision["reason"] == "missing_ticket"
    assert behavior["shadow_review:missing_ticket"] == 1
    assert shadow is not None and shadow["reason"] == "missing_ticket"


async def test_var_records_invalid_and_duplicate_document_hil_audit_entries() -> None:
    var = Var(action_semantics=_semantics())
    base = {
        "producer_principal": "Saga",
        "kind": "document_ingestion",
        "audited_topic": "object.verdict",
        "stage": "protection_check",
        "decision": "hil",
        "correlation_id": "doc-corr",
        "idempotency_key": "doc-corr:hil",
        "document_id": "document-1",
        "upload_id": "upload-1",
    }

    await var.on_typed_message("object.audit-entry", {**base, "upload_id": ""})
    await var.on_typed_message("object.audit-entry", base)
    await var.on_typed_message("object.audit-entry", base)

    behavior = var.behavior_snapshot()
    assert behavior["document_ticket_invalid"] == 1
    assert behavior["document_ticket_pending"] == 1
    assert behavior["document_ticket_duplicate"] == 1


async def test_bragi_records_ignored_duplicate_and_distinct_progress_identity() -> None:
    bragi = Bragi()

    await bragi.on_typed_message(
        "object.approval",
        {"correlation_id": "corr-progress", "idempotency_key": "approval-1"},
    )
    first = {
        "correlation_id": "corr-progress",
        "idempotency_key": "run-1",
        "state": "executing",
        "action_type": "ops.restart-service",
        "outcome": "pending",
    }
    second = {**first, "idempotency_key": "run-2"}
    await bragi.on_typed_message("object.action-run", first)
    await bragi.on_typed_message("object.action-run", first)
    await bragi.on_typed_message("object.action-run", second)

    behavior = bragi.behavior_snapshot()
    assert behavior["progress:ignored_topic"] == 1
    assert behavior["progress:recorded"] == 2
    assert behavior["progress:duplicate"] == 1
    assert [entry["idempotency_key"] for entry in bragi.progress_for("corr-progress")] == [
        "run-1",
        "run-2",
    ]


async def test_saga_records_republication_gaps_and_stamps_shadow_observation_time() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    fixed = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
    saga = Saga(clock=lambda: fixed)
    saga.bind_bus(bus)

    await saga.on_typed_message(
        "object.rule",
        {
            "producer_principal": "Mimir",
            "kind": "catalog_review_outcome",
            "idempotency_key": "catalog-review-1",
        },
    )
    await saga.on_typed_message(
        "object.forecast-outcome",
        {
            "producer_principal": "Heimdall",
            "correlation_id": "forecast-corr",
            "idempotency_key": "forecast-outcome-1",
        },
    )
    await saga.on_typed_message(
        "object.verdict",
        {
            "producer_principal": "Forseti",
            "kind": "document_ingestion",
            "idempotency_key": "doc-decision-1",
        },
    )
    await saga.on_typed_message(
        "object.approval",
        {
            "producer_principal": "Var",
            "kind": "document_ingestion",
            "idempotency_key": "doc-approval-1",
        },
    )
    await saga.on_typed_message(
        "object.action-run",
        {
            "producer_principal": "Thor",
            "correlation_id": "shadow-failed",
            "idempotency_key": "shadow-failed:terminal",
            "action_type": "ops.restart-service",
            "resource_id": "resource-1",
            "state": "failed",
            "shadow_mode": True,
        },
    )

    behavior = saga.behavior_snapshot()
    assert behavior["catalog_review_audit:missing_correlation"] == 1
    assert behavior["forecast_outcome_audit:missing_outcome_id"] == 1
    assert behavior["document_decision_audit:missing_correlation"] == 1
    assert behavior["document_approval_audit:missing_correlation"] == 1
    audit = [
        message.payload
        for message in bus.messages_on("object.audit-entry")
        if message.payload.get("shadow_observation_id") == "shadow-failed"
    ][0]
    assert audit["observed_at"] == fixed.isoformat()

    transportless = Saga()
    await transportless.on_typed_message(
        "object.rule",
        {
            "producer_principal": "Mimir",
            "kind": "catalog_review_outcome",
            "correlation_id": "catalog-corr",
            "idempotency_key": "catalog-review-2",
        },
    )
    assert transportless.behavior_snapshot()["catalog_review_audit:transport_unavailable"] == 1


async def test_mimir_records_ignored_and_rejected_owner_contract_failures() -> None:
    mimir = Mimir()

    await mimir.on_typed_message(
        "object.policy",
        {"correlation_id": "ignored", "idempotency_key": "ignored"},
    )
    with pytest.raises(ValueError, match="Mimir"):
        await mimir.on_typed_message(
            RULE_GENERATION_BUILD_REQUEST_TOPIC,
            {
                "producer_principal": "Mallory",
                "correlation_id": "build-corr",
                "idempotency_key": "build-key",
            },
        )
    with pytest.raises(ValueError, match="Heimdall"):
        await mimir.on_typed_message(
            "object.retrieval-validation",
            {
                "producer_principal": "Mallory",
                "event_type": "rule.semantic_generation.validation.completed.v1",
                "correlation_id": "validation-corr",
                "idempotency_key": "validation-key",
            },
        )

    behavior = mimir.behavior_snapshot()
    assert behavior["typed_message:ignored"] == 1
    assert behavior["rule_generation_build_request:rejected_owner"] == 1
    assert behavior["rule_generation_validation:rejected_owner"] == 1


async def test_muninn_rejects_keyless_bragi_and_identity_incomplete_change_projections() -> None:
    muninn = Muninn()

    await muninn.on_typed_message(
        "object.conversation",
        {
            "producer_principal": "Bragi",
            "conversation_id": "conversation-1",
            "correlation_id": "conversation-corr",
        },
    )
    await muninn.on_typed_message(
        "object.user-preference",
        {
            "producer_principal": "Bragi",
            "id": "preference-1",
            "correlation_id": "preference-corr",
            "preference_digest": "a" * 64,
        },
    )
    await muninn.on_typed_message(
        "object.change",
        {
            "producer_principal": "Huginn",
            "id": "change-1",
            "change_type": "updated",
        },
    )

    behavior = muninn.behavior_snapshot()
    assert behavior["conversation:missing_idempotency_key"] == 1
    assert behavior["user_preference:missing_idempotency_key"] == 1
    assert behavior["change:missing_identity"] == 1
    assert muninn.state_store.data.get("conversations", {}) == {}
    assert muninn.state_store.data.get("user_preferences", {}) == {}
    assert muninn.state_store.data.get("changes", {}) == {}


async def test_muninn_pattern_reads_record_invalid_unavailable_and_stale_noops() -> None:
    muninn = Muninn()

    assert (
        await muninn.read_operating_pattern(
            cohort_key="bad",
            pattern_id="a" * 64,
            access_scope_digest="b" * 64,
            purpose="purpose",
        )
        is None
    )
    assert muninn.behavior_snapshot()["operating_pattern_read:unavailable"] == 1

    muninn._durable_state_store = object()  # type: ignore[assignment]
    muninn._case_history = object()  # type: ignore[assignment]
    assert (
        await muninn.read_operating_pattern(
            cohort_key="bad",
            pattern_id="a" * 64,
            access_scope_digest="b" * 64,
            purpose="purpose",
        )
        is None
    )
    assert muninn.behavior_snapshot()["operating_pattern_read:invalid"] == 1


async def test_norns_records_learning_noops() -> None:
    norns = Norns(forecast_error_threshold=2)
    payload = {
        "producer_principal": "Muninn",
        "kind": "forecast_case_history",
        "correlation_id": "forecast-corr",
        "idempotency_key": "forecast-case-1",
        "case_id": "case-1",
        "revision": "1",
        "manifest_digest": "a" * 64,
        "detector_id": "detector-1",
        "metric": "latency",
        "outcome_label": "false_positive",
        "case_ref": f"case-history:case-1:1:{'a' * 64}",
    }

    await norns.on_typed_message(
        "object.event",
        {"correlation_id": "ignored", "idempotency_key": "ignored"},
    )
    await norns.on_typed_message(
        "object.context-index",
        {
            "producer_principal": "Muninn",
            "kind": "unsupported",
            "correlation_id": "unsupported",
            "idempotency_key": "unsupported",
        },
    )
    await norns.on_typed_message("object.context-index", payload)
    await norns.on_typed_message("object.context-index", payload)
    await norns.on_typed_message(
        "object.context-index",
        {**payload, "case_id": "case-2", "idempotency_key": "forecast-case-2"},
    )
    await norns.on_typed_message(
        "object.context-index",
        {**payload, "case_id": "case-3", "idempotency_key": "forecast-case-3"},
    )
    await norns.on_typed_message(
        "object.issue",
        {"producer_principal": "Saga", "correlation_id": "issue", "idempotency_key": "issue"},
    )
    await norns.on_typed_message(
        "object.audit-entry",
        {
            "producer_principal": "Saga",
            "correlation_id": "audit",
            "idempotency_key": "audit",
            "result": "failed",
        },
    )
    await norns.on_typed_message(
        "object.approval",
        {
            "producer_principal": "Var",
            "correlation_id": "approval",
            "idempotency_key": "approval",
        },
    )

    behavior = norns.behavior_snapshot()
    assert behavior["typed_message:ignored"] == 1
    assert behavior["context_index:unsupported_kind"] == 1
    assert behavior["forecast_case:collecting"] == 1
    assert behavior["forecast_case:duplicate"] == 1
    assert behavior["forecast_case:already_proposed"] == 1
    assert behavior["fingerprint:invalid"] == 1
    assert behavior["audit_outcome:invalid_target"] == 1
    assert behavior["approval:invalid"] == 1


def test_inmemory_bus_dead_letter_preserves_producer_and_names_failing_consumer() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    seen: list[str] = []

    async def boom(_topic: str, _payload: dict[str, object]) -> None:
        raise RuntimeError("boom")

    async def good(_topic: str, _payload: dict[str, object]) -> None:
        seen.append("good")

    bus.subscribe("object.event", "Heimdall", boom)
    bus.subscribe("object.event", "Forseti", good)

    asyncio.run(
        bus.publish(
            "Huginn",
            "object.event",
            {"correlation_id": "bus-corr", "idempotency_key": "bus-key"},
        )
    )

    assert seen == ["good"]
    assert len(bus.dead_letters) == 1
    assert bus.dead_letters[0].principal == "Huginn"
    assert bus.dead_letters[0].failing_consumer == "Heimdall"
