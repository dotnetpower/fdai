"""Wave 2 governance staff behavior tests."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fdai.agents._framework.adapters import (
    AuditChainError,
    InMemoryAuditChain,
    InMemoryGithubIssueAdapter,
)
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga, compute_fingerprint
from fdai.core.rule_semantic_generation import (
    RULE_GENERATION_ACTIVATION_COMMAND_TOPIC,
    RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
    RuleGenerationActivationBinder,
    StateStoreRuleGenerationOutboxLedger,
)
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RuleGenerationActivationResultEvent,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from pydantic import ValidationError

from tests.core.rule_semantic_generation.test_activation import _command, _CountingIndex
from tests.core.rule_semantic_generation.test_ledger import _result

# ---------------------------------------------------------------------------
# Saga - audit chain + issue dedup
# ---------------------------------------------------------------------------


def test_saga_audit_chain_appends_hash_linked_entries() -> None:
    saga = Saga()
    asyncio.run(
        saga.on_typed_message(
            "object.verdict",
            {
                "producer_principal": "Forseti",
                "correlation_id": "corr-1",
                "risk_verdict": "auto",
            },
        )
    )
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {
                "producer_principal": "Thor",
                "correlation_id": "corr-1",
                "state": "succeeded",
            },
        )
    )
    assert len(saga.audit_chain.entries) == 2
    saga.audit_chain.verify()


def test_saga_does_not_stringify_missing_correlation() -> None:
    saga = Saga()

    asyncio.run(
        saga.on_typed_message(
            "object.verdict",
            {
                "producer_principal": "Forseti",
                "correlation_id": None,
                "risk_verdict": "abstain",
            },
        )
    )

    assert saga.audit_chain.entries[0].correlation_id == ""


def test_saga_seals_document_admission_as_audit_entry() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    saga = Saga()
    saga.bind_bus(bus)

    asyncio.run(
        saga.on_typed_message(
            "object.verdict",
            {
                "producer_principal": "Forseti",
                "kind": "document_ingestion",
                "stage": "received",
                "decision": "admit",
                "reason": "ingress_validated",
                "correlation_id": "upload-1",
                "idempotency_key": "document.received:version-1",
                "document_id": "doc-1",
                "upload_id": "upload-1",
            },
        )
    )

    entry = bus.messages_on("object.audit-entry")[0].payload
    assert entry["producer_principal"] == "Saga"
    assert entry["audited_topic"] == "object.verdict"
    assert entry["kind"] == "document_ingestion"
    assert entry["stage"] == "received"
    assert entry["decision"] == "admit"
    assert "record" not in entry


def test_saga_seals_document_human_approval() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    saga = Saga()
    saga.bind_bus(bus)

    asyncio.run(
        saga.on_typed_message(
            "object.approval",
            {
                "producer_principal": "Var",
                "kind": "document_ingestion",
                "stage": "protection_check",
                "state": "approved",
                "correlation_id": "upload-hil",
                "document_id": "doc-hil",
                "upload_id": "upload-hil",
                "approvers": ["reviewer@example.com"],
                "idempotency_key": "document.inspected:version-hil",
            },
        )
    )

    entry = bus.messages_on("object.audit-entry")[0].payload
    assert entry["audited_topic"] == "object.approval"
    assert entry["decision"] == "approved"
    assert entry["approvers"] == ["reviewer@example.com"]
    assert entry["idempotency_key"] == "document.inspected:version-hil"


def test_saga_audit_chain_detects_tamper() -> None:
    chain = InMemoryAuditChain()
    chain.append(principal="Thor", topic="object.action-run", correlation_id="c", payload={})
    chain.append(principal="Thor", topic="object.action-run", correlation_id="c", payload={})
    # Tamper: mutate a payload_digest in place (frozen dataclass -> replace via list)
    tampered = chain.entries[1]
    chain.entries[1] = tampered.__class__(
        seq=tampered.seq,
        prev_hash=tampered.prev_hash,
        entry_hash=tampered.entry_hash,
        principal=tampered.principal,
        topic=tampered.topic,
        correlation_id=tampered.correlation_id,
        payload_digest="deadbeef",
    )
    with pytest.raises(AuditChainError):
        chain.verify()


def test_saga_issue_dedup_creates_once_and_appends_comment_on_repeat() -> None:
    saga = Saga()
    fp = compute_fingerprint(
        intent_category="cost_query_failed",
        resource_type="storage_account",
        normalized_selector="public_network_field",
        primary_agent="Heimdall",
        failure_reason_code="no_owned_data",
    )
    first = asyncio.run(
        saga.escalate_to_github_issue(
            fingerprint=fp,
            emitting_agent="Heimdall",
            intent_category="cost_query_failed",
            failure_reason_code="no_owned_data",
            correlation_id="corr-1",
        )
    )
    second = asyncio.run(
        saga.escalate_to_github_issue(
            fingerprint=fp,
            emitting_agent="Heimdall",
            intent_category="cost_query_failed",
            failure_reason_code="no_owned_data",
            correlation_id="corr-2",
        )
    )
    assert first["created"] is True
    assert second["created"] is False
    assert second["issue_number"] == first["issue_number"]
    assert second["occurrence_count"] == 2
    # Muninn index reflects the count
    idx = saga.state_store.get("issue_fingerprint_index", fp)
    assert idx is not None
    assert idx["occurrence_count"] == 2


def test_saga_direct_issue_operation_replay_is_idempotent() -> None:
    saga = Saga()
    fp = compute_fingerprint(
        intent_category="cost_query_failed",
        resource_type="storage_account",
        normalized_selector="public_network_field",
        primary_agent="Heimdall",
        failure_reason_code="no_owned_data",
    )

    first = asyncio.run(
        saga.escalate_to_github_issue(
            fingerprint=fp,
            emitting_agent="Heimdall",
            intent_category="cost_query_failed",
            failure_reason_code="no_owned_data",
            correlation_id="same-correlation",
        )
    )
    replay = asyncio.run(
        saga.escalate_to_github_issue(
            fingerprint=fp,
            emitting_agent="Heimdall",
            intent_category="cost_query_failed",
            failure_reason_code="no_owned_data",
            correlation_id="same-correlation",
        )
    )

    assert replay == first
    assert saga.github.issues[fp].comments == []


def test_saga_handoff_redelivery_is_idempotent() -> None:
    saga = Saga()
    saga.bind_bus(InMemoryBus(registry=load_pantheon()))
    payload = {
        "producer_principal": "Bragi",
        "id": "handoff-1",
        "escalation_id": "handoff-1",
        "correlation_id": "corr-1",
        "emitting_agent": "Bragi",
        "intent_category": "no_route",
        "normalized_selector": "sha256:selector",
        "failure_reason_code": "no_route",
    }

    asyncio.run(saga.on_typed_message("object.handoff-escalation", payload))
    asyncio.run(saga.on_typed_message("object.handoff-escalation", payload))

    assert len(saga.github.issues) == 1
    issue = next(iter(saga.github.issues.values()))
    assert issue.comments == []
    assert saga.behavior_snapshot()["handoff:duplicate"] == 1


def test_saga_durable_handoff_does_not_mirror_unused_local_receipt() -> None:
    store = InMemoryStateStore()
    saga = Saga(durable_state_store=store)
    saga.bind_bus(InMemoryBus(registry=load_pantheon()))
    payload = {
        "producer_principal": "Bragi",
        "id": "handoff-no-local-receipt",
        "escalation_id": "handoff-no-local-receipt",
        "correlation_id": "corr-no-local-receipt",
        "emitting_agent": "Bragi",
        "intent_category": "no_route",
        "normalized_selector": "sha256:selector",
        "failure_reason_code": "no_route",
    }

    asyncio.run(saga.on_typed_message("object.handoff-escalation", payload))

    assert (
        saga.state_store.get(
            "handoff_escalation_receipts",
            "handoff-no-local-receipt",
        )
        is None
    )


def test_saga_busless_handoff_resumes_publication_after_binding() -> None:
    store = InMemoryStateStore()
    saga = Saga(durable_state_store=store)
    payload = {
        "producer_principal": "Bragi",
        "id": "handoff-late-bus",
        "escalation_id": "handoff-late-bus",
        "correlation_id": "corr-late-bus",
        "emitting_agent": "Bragi",
        "intent_category": "no_route",
        "normalized_selector": "sha256:selector",
        "failure_reason_code": "no_route",
    }

    with pytest.raises(RuntimeError, match="publication bus is unavailable"):
        asyncio.run(saga.on_typed_message("object.handoff-escalation", payload))

    bus = InMemoryBus(registry=load_pantheon())
    saga.bind_bus(bus)
    asyncio.run(saga.on_typed_message("object.handoff-escalation", payload))
    asyncio.run(saga.on_typed_message("object.handoff-escalation", payload))

    assert len(bus.messages_on("object.issue")) == 1
    assert saga.behavior_snapshot()["handoff:publication_pending"] == 1
    assert saga.behavior_snapshot()["handoff:duplicate"] == 1


def test_saga_handoff_requires_idempotent_issue_adapter() -> None:
    class _LegacyIssueTracker:
        def __init__(self) -> None:
            self.issues = {}

        def create_or_comment(self, *, fingerprint, title, body):  # noqa: ANN001, ANN201
            raise AssertionError("non-idempotent issue mutation MUST NOT run")

        def close(self, fingerprint, *, closed_by_pr):  # noqa: ANN001, ANN201
            del fingerprint, closed_by_pr

    saga = Saga(github=_LegacyIssueTracker())
    payload = {
        "producer_principal": "Bragi",
        "id": "handoff-legacy-adapter",
        "escalation_id": "handoff-legacy-adapter",
        "correlation_id": "corr-legacy-adapter",
        "emitting_agent": "Bragi",
        "intent_category": "no_route",
        "normalized_selector": "sha256:selector",
        "failure_reason_code": "no_route",
    }

    with pytest.raises(RuntimeError, match="requires an idempotent issue-tracker adapter"):
        asyncio.run(saga.on_typed_message("object.handoff-escalation", payload))


def test_saga_completed_handoff_rejects_conflicting_redelivery() -> None:
    store = InMemoryStateStore()
    saga = Saga(durable_state_store=store)
    saga.bind_bus(InMemoryBus(registry=load_pantheon()))
    payload = {
        "producer_principal": "Bragi",
        "id": "handoff-conflict",
        "escalation_id": "handoff-conflict",
        "correlation_id": "corr-conflict",
        "emitting_agent": "Bragi",
        "intent_category": "no_route",
        "normalized_selector": "sha256:selector",
        "failure_reason_code": "no_route",
    }

    asyncio.run(saga.on_typed_message("object.handoff-escalation", payload))

    with pytest.raises(ValueError, match="conflicts with its durable claim"):
        asyncio.run(
            saga.on_typed_message(
                "object.handoff-escalation",
                {**payload, "failure_reason_code": "different_reason"},
            )
        )


def test_saga_rejects_malformed_completion_receipt() -> None:
    store = InMemoryStateStore()
    payload = {
        "producer_principal": "Bragi",
        "id": "handoff-malformed-receipt",
        "escalation_id": "handoff-malformed-receipt",
        "correlation_id": "corr-malformed-receipt",
        "emitting_agent": "Bragi",
        "intent_category": "no_route",
        "normalized_selector": "sha256:selector",
        "failure_reason_code": "no_route",
    }
    first = Saga(durable_state_store=store)
    first.bind_bus(InMemoryBus(registry=load_pantheon()))
    asyncio.run(first.on_typed_message("object.handoff-escalation", payload))
    digest = hashlib.sha256(b"handoff-malformed-receipt").hexdigest()
    receipt_key = f"pantheon/saga/handoff/{digest}/receipt"
    asyncio.run(store.write_state(receipt_key, {"schema_version": "invalid"}))

    with pytest.raises(ValueError, match="completion receipt is malformed"):
        asyncio.run(
            Saga(durable_state_store=store).on_typed_message(
                "object.handoff-escalation",
                payload,
            )
        )


def test_saga_rejects_malformed_mutation_checkpoint() -> None:
    class _FailIssueAudit(InMemoryAuditChain):
        def append(self, *, principal, topic, correlation_id, payload):  # noqa: ANN001, ANN201
            if topic == "object.issue":
                raise RuntimeError("stop after mutation checkpoint")
            return super().append(
                principal=principal,
                topic=topic,
                correlation_id=correlation_id,
                payload=payload,
            )

    store = InMemoryStateStore()
    github = InMemoryGithubIssueAdapter()
    payload = {
        "producer_principal": "Bragi",
        "id": "handoff-malformed-checkpoint",
        "escalation_id": "handoff-malformed-checkpoint",
        "correlation_id": "corr-malformed-checkpoint",
        "emitting_agent": "Bragi",
        "intent_category": "no_route",
        "normalized_selector": "sha256:selector",
        "failure_reason_code": "no_route",
    }
    with pytest.raises(RuntimeError, match="stop after mutation checkpoint"):
        asyncio.run(
            Saga(
                audit_chain=_FailIssueAudit(),
                durable_state_store=store,
                github=github,
            ).on_typed_message("object.handoff-escalation", payload)
        )
    digest = hashlib.sha256(b"handoff-malformed-checkpoint").hexdigest()
    checkpoint_key = f"pantheon/saga/handoff/{digest}/checkpoint"
    asyncio.run(store.write_state(checkpoint_key, {"schema_version": "invalid"}))

    with pytest.raises(ValueError, match="handoff checkpoint is malformed"):
        asyncio.run(
            Saga(durable_state_store=store, github=github).on_typed_message(
                "object.handoff-escalation",
                payload,
            )
        )
    assert github.operation_results.keys() == {"handoff:handoff-malformed-checkpoint"}
    assert next(iter(github.issues.values())).comments == []


def test_saga_cross_instance_handoff_uses_one_external_operation() -> None:
    class _ConcurrentIssueTracker(InMemoryGithubIssueAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.arrivals = 0
            self.ready = asyncio.Event()

        async def create_or_comment_once(
            self,
            *,
            operation_id,
            fingerprint,
            title,
            body,
        ):  # noqa: ANN001, ANN201
            self.arrivals += 1
            if self.arrivals == 2:
                self.ready.set()
            await self.ready.wait()
            return super().create_or_comment_once(
                operation_id=operation_id,
                fingerprint=fingerprint,
                title=title,
                body=body,
            )

    async def _run() -> tuple[Saga, Saga, _ConcurrentIssueTracker]:
        store = InMemoryStateStore()
        github = _ConcurrentIssueTracker()
        first = Saga(durable_state_store=store, github=github)
        second = Saga(durable_state_store=store, github=github)
        bus = InMemoryBus(registry=load_pantheon())
        first.bind_bus(bus)
        second.bind_bus(bus)
        payload = {
            "producer_principal": "Bragi",
            "id": "handoff-concurrent-replicas",
            "escalation_id": "handoff-concurrent-replicas",
            "correlation_id": "corr-concurrent-replicas",
            "emitting_agent": "Bragi",
            "intent_category": "no_route",
            "normalized_selector": "sha256:selector",
            "failure_reason_code": "no_route",
        }
        await asyncio.gather(
            first.on_typed_message("object.handoff-escalation", payload),
            second.on_typed_message("object.handoff-escalation", payload),
        )
        return first, second, github

    first, second, github = asyncio.run(_run())

    assert github.arrivals == 2
    assert github.operation_results.keys() == {"handoff:handoff-concurrent-replicas"}
    assert len(github.issues) == 1
    assert next(iter(github.issues.values())).comments == []
    assert first.behavior_snapshot()["handoff:materialized"] == 1
    assert second.behavior_snapshot()["handoff:materialized"] == 1


def test_saga_handoff_audit_retry_does_not_duplicate_github_mutation() -> None:
    class _FailOnceIssueAudit(InMemoryAuditChain):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        def append(self, *, principal, topic, correlation_id, payload):  # noqa: ANN001, ANN201
            if topic == "object.issue" and not self.failed:
                self.failed = True
                raise RuntimeError("audit unavailable")
            return super().append(
                principal=principal,
                topic=topic,
                correlation_id=correlation_id,
                payload=payload,
            )

    chain = _FailOnceIssueAudit()
    store = InMemoryStateStore()
    github = InMemoryGithubIssueAdapter()
    saga = Saga(
        audit_chain=chain,
        durable_state_store=store,
        github=github,
    )
    payload = {
        "producer_principal": "Bragi",
        "id": "handoff-audit-retry",
        "escalation_id": "handoff-audit-retry",
        "correlation_id": "corr-audit-retry",
        "emitting_agent": "Bragi",
        "intent_category": "no_route",
        "normalized_selector": "sha256:selector",
        "failure_reason_code": "no_route",
    }

    with pytest.raises(RuntimeError, match="audit unavailable"):
        asyncio.run(saga.on_typed_message("object.handoff-escalation", payload))
    restarted = Saga(
        audit_chain=chain,
        durable_state_store=store,
        github=github,
    )
    restarted.bind_bus(InMemoryBus(registry=load_pantheon()))
    asyncio.run(restarted.on_typed_message("object.handoff-escalation", payload))

    issue = next(iter(github.issues.values()))
    assert issue.comments == []
    assert len([entry for entry in chain.entries if entry.topic == "object.issue"]) == 1
    assert restarted.behavior_snapshot()["handoff:materialized"] == 1


def test_saga_external_operation_id_closes_precheckpoint_crash_window() -> None:
    class _FailOnceCheckpointStore(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        async def write_state(self, key, value):  # noqa: ANN001, ANN201
            if key.endswith("/checkpoint") and not self.failed:
                self.failed = True
                raise RuntimeError("checkpoint unavailable")
            await super().write_state(key, value)

    store = _FailOnceCheckpointStore()
    github = InMemoryGithubIssueAdapter()
    payload = {
        "producer_principal": "Bragi",
        "id": "handoff-checkpoint-retry",
        "escalation_id": "handoff-checkpoint-retry",
        "correlation_id": "corr-checkpoint-retry",
        "emitting_agent": "Bragi",
        "intent_category": "no_route",
        "normalized_selector": "sha256:selector",
        "failure_reason_code": "no_route",
    }
    first = Saga(durable_state_store=store, github=github)

    with pytest.raises(RuntimeError, match="checkpoint unavailable"):
        asyncio.run(first.on_typed_message("object.handoff-escalation", payload))

    restarted = Saga(durable_state_store=store, github=github)
    restarted.bind_bus(InMemoryBus(registry=load_pantheon()))
    asyncio.run(restarted.on_typed_message("object.handoff-escalation", payload))

    issue = next(iter(github.issues.values()))
    assert issue.comments == []
    assert restarted.behavior_snapshot()["handoff:materialized"] == 1


def test_saga_handoff_publication_retry_does_not_repeat_audit_or_github() -> None:
    class _FailOnceIssueBus:
        def __init__(self) -> None:
            self.publish_calls = 0
            self.payloads: list[dict[str, object]] = []

        def subscribe(self, topic, agent_name, handler):  # noqa: ANN001, ANN201
            del topic, agent_name, handler

        async def publish(self, principal, topic, payload):  # noqa: ANN001, ANN201
            self.publish_calls += 1
            if self.publish_calls == 1:
                raise RuntimeError("bus unavailable")
            assert principal == "Saga"
            assert topic == "object.issue"
            self.payloads.append(dict(payload))

    chain = InMemoryAuditChain()
    bus = _FailOnceIssueBus()
    saga = Saga(audit_chain=chain)
    saga.bind_bus(bus)
    payload = {
        "producer_principal": "Bragi",
        "id": "handoff-publish-retry",
        "escalation_id": "handoff-publish-retry",
        "correlation_id": "corr-publish-retry",
        "emitting_agent": "Bragi",
        "intent_category": "no_route",
        "normalized_selector": "sha256:selector",
        "failure_reason_code": "no_route",
    }

    with pytest.raises(RuntimeError, match="bus unavailable"):
        asyncio.run(saga.on_typed_message("object.handoff-escalation", payload))
    asyncio.run(saga.on_typed_message("object.handoff-escalation", payload))

    issue = next(iter(saga.github.issues.values()))
    assert issue.comments == []
    assert len([entry for entry in chain.entries if entry.topic == "object.issue"]) == 1
    assert bus.publish_calls == 2
    assert bus.payloads[0]["idempotency_key"] == "handoff:handoff-publish-retry"


def test_saga_close_issue_records_promoting_pr() -> None:
    saga = Saga()
    fp = compute_fingerprint(
        intent_category="x",
        resource_type="y",
        normalized_selector="z",
        primary_agent="Bragi",
        failure_reason_code="low_confidence",
    )
    asyncio.run(
        saga.escalate_to_github_issue(
            fingerprint=fp,
            emitting_agent="Bragi",
            intent_category="x",
            failure_reason_code="low_confidence",
            correlation_id="corr-close",
        )
    )
    asyncio.run(saga.close_issue(fingerprint=fp, closed_by_pr="https://example.invalid/pr/42"))
    issue = saga.github.issues[fp]
    assert issue.open is False
    assert issue.closed_by_pr == "https://example.invalid/pr/42"


def test_saga_replay_returns_ordered_slice_for_correlation() -> None:
    saga = Saga()
    for i in range(3):
        asyncio.run(
            saga.on_typed_message(
                "object.action-run",
                {"producer_principal": "Thor", "correlation_id": "keep", "seq": i},
            )
        )
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {"producer_principal": "Thor", "correlation_id": "other", "seq": 99},
        )
    )
    slice_entries = saga.replay_for_correlation("keep")
    assert len(slice_entries) == 3
    assert [e.correlation_id for e in slice_entries] == ["keep"] * 3


def test_saga_escalate_renders_context_lines_in_issue_body() -> None:
    saga = Saga()
    fp = compute_fingerprint(
        intent_category="cost_query_failed",
        resource_type="storage_account",
        normalized_selector="sel",
        primary_agent="Heimdall",
        failure_reason_code="no_owned_data",
    )
    asyncio.run(
        saga.escalate_to_github_issue(
            fingerprint=fp,
            emitting_agent="Heimdall",
            intent_category="cost_query_failed",
            failure_reason_code="no_owned_data",
            correlation_id="corr-ctx",
            context={"resource_id": "vm-9", "region": "koreacentral"},
        )
    )
    body = saga.github.issues[fp].body
    # Context items are rendered as sorted bullet lines in the issue body.
    assert "- region: koreacentral" in body
    assert "- resource_id: vm-9" in body


def test_saga_introspect_scoped_and_general() -> None:
    saga = Saga()
    for i in range(2):
        asyncio.run(
            saga.on_typed_message(
                "object.action-run",
                {"producer_principal": "Thor", "correlation_id": "keep", "seq": i},
            )
        )

    # Naming a known correlation id scopes the answer to its entries.
    scoped = asyncio.run(saga.introspect("what happened for keep?", {}))
    assert scoped.facts["correlation_id"] == "keep"
    assert len(scoped.facts["matched_entries"]) == 2
    assert "Thor" in scoped.answer

    # No correlation named -> a general "latest entry" summary.
    general = asyncio.run(saga.introspect("give me an audit overview", {}))
    assert general.facts["audit_entries"] == 2
    assert "latest" in general.answer


def test_saga_introspect_empty_chain() -> None:
    saga = Saga()
    result = asyncio.run(saga.introspect("anything recorded?", {}))
    assert result.facts["audit_entries"] == 0
    assert "empty" in result.answer


# ---------------------------------------------------------------------------
# Muninn - context store
# ---------------------------------------------------------------------------


def test_muninn_indexes_conversation_turns() -> None:
    muninn = Muninn()
    asyncio.run(
        muninn.on_typed_message(
            "object.turn",
            {"turn_id": "t1", "question": "hi", "answer": "hello"},
        )
    )
    stored = muninn.get_context("conversation_turns", "t1")
    assert stored is not None
    assert stored["question"] == "hi"


def test_muninn_requests_index_after_saga_sealed_document_admit() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    muninn = Muninn()
    muninn.bind_bus(bus)

    asyncio.run(
        muninn.on_typed_message(
            "object.audit-entry",
            {
                "producer_principal": "Saga",
                "kind": "document_ingestion",
                "audited_topic": "object.verdict",
                "stage": "protection_check",
                "decision": "admit",
                "correlation_id": "upload-1",
                "idempotency_key": "document.inspected:version-1",
                "document_id": "doc-1",
                "upload_id": "upload-1",
            },
        )
    )

    command = bus.messages_on("object.context-index")[0].payload
    assert command["producer_principal"] == "Muninn"
    assert command["kind"] == "document_ingestion"
    assert command["stage"] == "indexing"
    assert command["command"] == "index"
    assert command["upload_id"] == "upload-1"


def test_muninn_does_not_index_held_or_incomplete_documents() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    muninn = Muninn()
    muninn.bind_bus(bus)

    asyncio.run(
        muninn.on_typed_message(
            "object.audit-entry",
            {
                "kind": "document_ingestion",
                "audited_topic": "object.verdict",
                "stage": "protection_check",
                "decision": "hold",
            },
        )
    )

    assert bus.messages_on("object.context-index") == []


def test_muninn_requests_index_after_saga_sealed_human_approval() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    muninn = Muninn()
    muninn.bind_bus(bus)

    asyncio.run(
        muninn.on_typed_message(
            "object.audit-entry",
            {
                "producer_principal": "Saga",
                "kind": "document_ingestion",
                "audited_topic": "object.approval",
                "stage": "protection_check",
                "decision": "approved",
                "correlation_id": "upload-hil",
                "document_id": "doc-hil",
                "upload_id": "upload-hil",
            },
        )
    )

    assert bus.messages_on("object.context-index")[0].payload["command"] == "index"


def test_muninn_put_get_generic() -> None:
    muninn = Muninn()
    muninn.put_context("resource_state", "vm-1", {"public": False})
    assert muninn.get_context("resource_state", "vm-1") == {"public": False}
    assert muninn.get_context("resource_state", "missing") is None


def test_muninn_ignores_turn_without_id_and_other_topics() -> None:
    muninn = Muninn()
    # A turn payload with no id (neither turn_id nor id) is a no-op: nothing
    # is stored, so the conversation_turns bucket never materializes.
    asyncio.run(muninn.on_typed_message("object.turn", {"question": "hi"}))
    # An unrelated topic is ignored entirely.
    asyncio.run(muninn.on_typed_message("object.verdict", {"turn_id": "t9"}))
    assert muninn.get_context("conversation_turns", "t9") is None
    assert muninn.state_store.data == {}


def test_muninn_introspect_general_and_scoped() -> None:
    muninn = Muninn()
    # Bucket names are single tokens ([a-z0-9-]+) so the introspection
    # tokenizer can match one when the operator names it.
    muninn.put_context("vms", "vm-1", {"public": False})
    muninn.put_context("vms", "vm-2", {"public": True})
    muninn.put_context("costs", "rg-a", {"usd": 12})

    # No bucket named -> a general summary over all buckets/keys.
    general = asyncio.run(muninn.introspect("what state do you hold?", {}))
    assert general.facts["buckets_count"] == 2
    assert general.facts["total_keys"] == 3
    assert "2 state bucket" in general.answer

    # Naming an existing bucket scopes the answer to that bucket.
    scoped = asyncio.run(muninn.introspect("how many vms keys?", {}))
    assert scoped.facts["bucket"] == "vms"
    assert scoped.facts["key_count"] == 2
    assert "vms" in scoped.answer
    assert "2 key(s)" in scoped.answer


# ---------------------------------------------------------------------------
# Mimir - promotion state
# ---------------------------------------------------------------------------


def _mimir_with_bus() -> Mimir:
    mimir = Mimir()
    mimir.bind_bus(InMemoryBus(registry=load_pantheon()))
    return mimir


async def test_mimir_rule_generation_command_requires_bound_binder() -> None:
    command = _result().command

    with pytest.raises(RuntimeError, match="activation binder is unavailable"):
        await Mimir().on_typed_message(
            RULE_GENERATION_ACTIVATION_COMMAND_TOPIC,
            command.model_dump(mode="json"),
        )


async def test_mimir_rejects_malformed_rule_generation_command_before_delegation() -> None:
    command = _result().command
    malformed = command.model_dump(mode="json")
    malformed["command_digest"] = "sha256:" + "0" * 64
    handle = AsyncMock()
    mimir = Mimir()
    mimir.bind_rule_generation_activation_binder(
        cast(RuleGenerationActivationBinder, type("Binder", (), {"handle": handle})())
    )

    with pytest.raises(ValidationError):
        await mimir.on_typed_message(RULE_GENERATION_ACTIVATION_COMMAND_TOPIC, malformed)

    handle.assert_not_awaited()


async def test_mimir_delegates_valid_rule_generation_command_once() -> None:
    command = _result().command
    handle = AsyncMock()
    mimir = Mimir()
    mimir.bind_rule_generation_activation_binder(
        cast(RuleGenerationActivationBinder, type("Binder", (), {"handle": handle})())
    )

    await mimir.on_typed_message(
        RULE_GENERATION_ACTIVATION_COMMAND_TOPIC,
        command.model_dump(mode="json"),
    )

    handle.assert_awaited_once_with(command)


async def test_mimir_rule_generation_command_redelivery_is_activation_effect_safe() -> None:
    index = _CountingIndex()
    command, metadata, documents = _command()
    await index.stage_generation(metadata, documents)
    mimir = Mimir()
    mimir.bind_rule_generation_activation_binder(
        RuleGenerationActivationBinder(
            index=index,
            ledger=StateStoreRuleGenerationOutboxLedger(store=InMemoryStateStore()),
        )
    )
    payload = command.model_dump(mode="json")

    await mimir.on_typed_message(RULE_GENERATION_ACTIVATION_COMMAND_TOPIC, payload)
    await mimir.on_typed_message(RULE_GENERATION_ACTIVATION_COMMAND_TOPIC, payload)

    assert index.activation_attempts == 1


async def test_mimir_rule_generation_result_never_invokes_activation_binder() -> None:
    result = _result()
    handle = AsyncMock()
    mimir = Mimir()
    mimir.bind_rule_generation_activation_binder(
        cast(RuleGenerationActivationBinder, type("Binder", (), {"handle": handle})())
    )
    mimir.bind_rule_generation_state_store(InMemoryStateStore())

    await mimir.on_typed_message(
        RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
        result.model_dump(mode="json"),
    )

    handle.assert_not_awaited()


async def test_mimir_records_rule_generation_result_as_no_authority_projection() -> None:
    store = InMemoryStateStore()
    mimir = Mimir()
    mimir.bind_rule_generation_state_store(store)
    result = _result()

    await mimir.on_typed_message(
        RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
        result.model_dump(mode="json"),
    )

    receipt = await store.read_state(
        f"mimir:rule-generation-activation-result:{result.idempotency_key}"
    )
    assert receipt is not None
    assert receipt["result_digest"] == result.result_digest
    assert receipt["projection_only"] is True
    assert receipt["grants_execution_authority"] is False
    assert len(tuple(store.audit_entries)) == 1
    assert await store.verify_chain()


async def test_mimir_rule_generation_result_redelivery_is_restart_safe() -> None:
    store = InMemoryStateStore()
    result = _result()
    payload = result.model_dump(mode="json")
    first = Mimir()
    first.bind_rule_generation_state_store(store)

    await asyncio.gather(
        first.on_typed_message(RULE_GENERATION_ACTIVATION_RESULT_TOPIC, payload),
        first.on_typed_message(RULE_GENERATION_ACTIVATION_RESULT_TOPIC, payload),
    )
    restarted = Mimir()
    restarted.bind_rule_generation_state_store(store)
    await restarted.on_typed_message(RULE_GENERATION_ACTIVATION_RESULT_TOPIC, payload)

    assert len(tuple(store.audit_entries)) == 1
    assert first.behavior_snapshot()["rule_generation_activation_result_recorded"] == 1
    assert first.behavior_snapshot()["rule_generation_activation_result_duplicate"] == 1
    assert restarted.behavior_snapshot()["rule_generation_activation_result_duplicate"] == 1


async def test_mimir_rejects_rule_generation_result_idempotency_conflict() -> None:
    store = InMemoryStateStore()
    mimir = Mimir()
    mimir.bind_rule_generation_state_store(store)
    result = _result()
    conflicting = RuleGenerationActivationResultEvent.create(
        command=result.command,
        status=result.status,
        completed_at=result.completed_at + timedelta(seconds=1),
    )

    await mimir.on_typed_message(
        RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
        result.model_dump(mode="json"),
    )
    with pytest.raises(ValueError, match="idempotency conflict"):
        await mimir.on_typed_message(
            RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
            conflicting.model_dump(mode="json"),
        )
    assert len(tuple(store.audit_entries)) == 1


async def test_mimir_rejects_malformed_or_unbound_rule_generation_result() -> None:
    result = _result()
    malformed = result.model_dump(mode="json")
    malformed["result_digest"] = "sha256:" + "0" * 64
    store = InMemoryStateStore()
    mimir = Mimir()
    mimir.bind_rule_generation_state_store(store)

    with pytest.raises(ValidationError):
        await mimir.on_typed_message(RULE_GENERATION_ACTIVATION_RESULT_TOPIC, malformed)
    with pytest.raises(RuntimeError, match="receipt store is unavailable"):
        await Mimir().on_typed_message(
            RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
            result.model_dump(mode="json"),
        )
    assert len(tuple(store.audit_entries)) == 0


def _proven_shadow_dwell(target: str) -> dict[str, object]:
    """Dwell evidence that clears the default discovery-loop bars for ``target``."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return {
        "target": target,
        "window_start": start.isoformat(),
        "window_end": (start + timedelta(days=30)).isoformat(),
        "sample_size": 200,
        "reviewed_count": 200,
        "agreed_count": 200,
        "policy_escapes": 0,
    }


def test_mimir_accepts_and_drains_rule_candidates() -> None:
    mimir = Mimir()
    asyncio.run(
        mimir.on_typed_message(
            "object.rule-candidate",
            {
                "idempotency_key": "candidate:storage-public-deny:1",
                "target_rule_id": "storage.public.deny",
                "proposal_kind": "new",
                "proposed_by": "Norns",
                "source_signal": "handoff_fingerprint",
                "evidence": {"fingerprint": "abc", "occurrence_count": 3},
                "shadow_dwell": _proven_shadow_dwell("storage.public.deny"),
            },
        )
    )
    assert len(mimir.pending_candidates()) == 1
    assert len(mimir.promotion_ready_candidates()) == 1
    mimir.promote("storage.public.deny", source="handoff")
    status = mimir.status("storage.public.deny")
    assert status is not None
    assert status.state == "enforce"
    # promoted candidate is removed from the pending list
    assert all(c.get("target_rule_id") != "storage.public.deny" for c in mimir.pending_candidates())


def test_mimir_quarantines_ungrounded_candidate() -> None:
    """A candidate with no evidence is quarantined, not accepted."""
    mimir = _mimir_with_bus()
    asyncio.run(
        mimir.on_typed_message(
            "object.rule-candidate",
            {
                "idempotency_key": "candidate:r1:ungrounded:1",
                "target_rule_id": "r1",
                "proposal_kind": "new",
                "proposed_by": "Norns",
            },
        )
    )
    assert mimir.pending_candidates() == ()
    quarantined = mimir.quarantined_candidates()
    assert len(quarantined) == 1
    assert quarantined[0]["quarantine_reason"] == "ungrounded:no_evidence"


def test_mimir_quarantines_missing_provenance() -> None:
    mimir = _mimir_with_bus()
    asyncio.run(
        mimir.on_typed_message(
            "object.rule-candidate",
            {
                "idempotency_key": "candidate:r1:missing-provenance:1",
                "target_rule_id": "r1",
                "proposal_kind": "new",
                "evidence": {"x": 1},
            },
        )
    )
    assert mimir.pending_candidates() == ()
    assert mimir.quarantined_candidates()[0]["quarantine_reason"] == (
        "missing_provenance:proposed_by"
    )


def test_mimir_quarantine_is_bounded_against_poisoning_flood() -> None:
    # Quarantine holds REJECTED candidates - attacker-controlled volume under a
    # poisoning attempt. It must be a bounded ring so a flood cannot exhaust
    # memory (DoS), while keeping the most recent rejects for diagnostics.
    from fdai.agents.mimir import _MAX_QUARANTINE

    mimir = _mimir_with_bus()
    for i in range(_MAX_QUARANTINE + 50):
        asyncio.run(
            mimir.on_typed_message(
                "object.rule-candidate",
                # No provenance -> guard rejects -> quarantined.
                {
                    "idempotency_key": f"candidate:r{i}:poisoning:1",
                    "target_rule_id": f"r{i}",
                    "proposal_kind": "new",
                    "evidence": {"x": 1},
                },
            )
        )
    assert len(mimir.quarantined_candidates()) == _MAX_QUARANTINE


def test_mimir_revoke_flips_state_to_retired() -> None:
    mimir = Mimir()
    mimir.promote("r1", source="manual")
    mimir.revoke("r1")
    assert mimir.status("r1").state == "retired"


# ---------------------------------------------------------------------------
# Norns - fingerprint aggregator
# ---------------------------------------------------------------------------


def test_norns_proposes_candidate_after_threshold() -> None:
    norns = Norns(promotion_threshold=3)
    payload = {"fingerprint": "abc123"}
    for _ in range(3):
        asyncio.run(norns.on_typed_message("object.issue", payload))
    assert norns.occurrences("abc123") == 3
    assert len(norns.pending_candidates) == 1
    assert norns.pending_candidates[0]["evidence"]["fingerprint"] == "abc123"


def test_norns_dedups_candidate_proposals() -> None:
    norns = Norns(promotion_threshold=2)
    payload = {"fingerprint": "same-fp"}
    for _ in range(5):
        asyncio.run(norns.on_typed_message("object.issue", payload))
    # Threshold crossed once, proposal must not repeat.
    assert len(norns.pending_candidates) == 1


def test_norns_dedups_replayed_issue_operation_before_counting() -> None:
    norns = Norns(promotion_threshold=2)
    replay = {
        "fingerprint": "replayed-fingerprint",
        "idempotency_key": "handoff:one-operation",
    }

    asyncio.run(norns.on_typed_message("object.issue", dict(replay)))
    asyncio.run(norns.on_typed_message("object.issue", dict(replay)))

    assert norns.occurrences("replayed-fingerprint") == 1
    assert norns.pending_candidates == []
    assert norns.behavior_snapshot()["issue_learning_duplicate"] == 1


def test_norns_durable_issue_dedup_survives_restart() -> None:
    store = InMemoryStateStore()
    payload = {
        "fingerprint": "durable-fingerprint",
        "idempotency_key": "handoff:durable-operation",
    }
    first = Norns(promotion_threshold=2, issue_state_store=store)
    restarted = Norns(promotion_threshold=2, issue_state_store=store)

    asyncio.run(first.on_typed_message("object.issue", dict(payload)))
    asyncio.run(restarted.on_typed_message("object.issue", dict(payload)))

    assert first.occurrences("durable-fingerprint") == 1
    assert restarted.occurrences("durable-fingerprint") == 1
    assert restarted.behavior_snapshot()["issue_learning_duplicate"] == 1


def test_norns_resumes_claim_interrupted_before_fingerprint_apply() -> None:
    class _FailFirstFingerprintApply(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        async def write_state_with_audit_if_absent(
            self,
            key,
            value,
            audit_entry,
        ):  # noqa: ANN001, ANN201
            if "/fingerprints/" in key and not self.failed:
                self.failed = True
                raise RuntimeError("fingerprint apply interrupted")
            return await super().write_state_with_audit_if_absent(
                key,
                value,
                audit_entry,
            )

        async def read_states(self, prefix, *, limit):  # noqa: ANN001, ANN201
            raise AssertionError(
                f"pending recovery MUST NOT scan terminal history: {prefix=} {limit=}"
            )

    store = _FailFirstFingerprintApply()
    payload = {
        "fingerprint": "interrupted-fingerprint",
        "idempotency_key": "handoff:interrupted-operation",
    }

    with pytest.raises(RuntimeError, match="fingerprint apply interrupted"):
        asyncio.run(
            Norns(
                promotion_threshold=1,
                issue_state_store=store,
            ).on_typed_message("object.issue", dict(payload))
        )

    restarted = Norns(promotion_threshold=1, issue_state_store=store)
    asyncio.run(restarted.on_typed_message("object.issue", dict(payload)))

    assert restarted.occurrences("interrupted-fingerprint") == 1
    assert len(restarted.pending_candidates) == 1
    assert restarted.pending_candidates[0]["evidence"]["fingerprint"] == "interrupted-fingerprint"


def test_norns_startup_recovers_pending_operation_without_redelivery() -> None:
    class _FailFirstFingerprintApply(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        async def write_state_with_audit_if_absent(
            self,
            key,
            value,
            audit_entry,
        ):  # noqa: ANN001, ANN201
            if "/fingerprints/" in key and not self.failed:
                self.failed = True
                raise RuntimeError("fingerprint apply interrupted")
            return await super().write_state_with_audit_if_absent(
                key,
                value,
                audit_entry,
            )

        async def read_states(self, prefix, *, limit):  # noqa: ANN001, ANN201
            raise AssertionError(
                f"pending recovery MUST NOT scan terminal history: {prefix=} {limit=}"
            )

    store = _FailFirstFingerprintApply()
    payload = {
        "fingerprint": "startup-operation-fingerprint",
        "idempotency_key": "handoff:startup-operation",
    }
    with pytest.raises(RuntimeError, match="fingerprint apply interrupted"):
        asyncio.run(
            Norns(
                promotion_threshold=2,
                issue_state_store=store,
            ).on_typed_message("object.issue", dict(payload))
        )

    restarted = Norns(promotion_threshold=2, issue_state_store=store)
    assert asyncio.run(restarted.recover_issue_learning()) == 0
    assert restarted.occurrences("startup-operation-fingerprint") == 1
    assert restarted.pending_candidates == []


def test_norns_rebuilds_pending_candidate_after_restart() -> None:
    store = InMemoryStateStore()
    payload = {
        "fingerprint": "pending-candidate-fingerprint",
        "idempotency_key": "handoff:pending-candidate-operation",
    }
    first = Norns(promotion_threshold=1, issue_state_store=store)
    asyncio.run(first.on_typed_message("object.issue", dict(payload)))
    assert len(first.pending_candidates) == 1

    restarted = Norns(promotion_threshold=1, issue_state_store=store)
    asyncio.run(restarted.on_typed_message("object.issue", dict(payload)))

    assert restarted.occurrences("pending-candidate-fingerprint") == 1
    assert len(restarted.pending_candidates) == 1


def test_norns_does_not_rebuild_delivered_candidate_after_restart() -> None:
    store = InMemoryStateStore()
    bus = InMemoryBus(registry=load_pantheon())
    payload = {
        "fingerprint": "delivered-candidate-fingerprint",
        "idempotency_key": "handoff:delivered-candidate-operation",
    }
    first = Norns(promotion_threshold=1, issue_state_store=store)
    first.bind_bus(bus)
    asyncio.run(first.on_typed_message("object.issue", dict(payload)))
    assert len(bus.messages_on("object.rule-candidate")) == 1

    restarted = Norns(promotion_threshold=1, issue_state_store=store)
    asyncio.run(restarted.on_typed_message("object.issue", dict(payload)))

    assert restarted.occurrences("delivered-candidate-fingerprint") == 1
    assert restarted.pending_candidates == []


def test_norns_public_flush_completes_durable_candidate_delivery() -> None:
    store = InMemoryStateStore()
    bus = InMemoryBus(registry=load_pantheon())
    enabled = [False]
    payload = {
        "fingerprint": "batch-flush-fingerprint",
        "idempotency_key": "handoff:batch-flush-operation",
    }
    norns = Norns(promotion_threshold=1, issue_state_store=store)
    norns.bind_bus(bus)
    norns.bind_candidate_publication_gate(lambda: enabled[0])
    asyncio.run(norns.on_typed_message("object.issue", dict(payload)))
    assert len(norns.pending_candidates) == 1

    enabled[0] = True
    assert asyncio.run(norns.flush_candidates()) == 1

    restarted = Norns(promotion_threshold=1, issue_state_store=store)
    asyncio.run(restarted.on_typed_message("object.issue", dict(payload)))
    assert restarted.pending_candidates == []


def test_norns_public_flush_recovers_candidates_behind_blocked_head() -> None:
    store = InMemoryStateStore()
    seed = Norns(promotion_threshold=1, issue_state_store=store)
    for cohort in range(2):
        asyncio.run(
            seed.on_typed_message(
                "object.issue",
                {
                    "fingerprint": f"blocked-fingerprint-{cohort}",
                    "idempotency_key": f"handoff:blocked-{cohort}",
                },
            )
        )
    assert len(seed.pending_candidates) == 2

    bus = InMemoryBus(registry=load_pantheon())
    enabled = [False]
    restarted = Norns(promotion_threshold=1, issue_state_store=store)
    restarted.bind_bus(bus)
    restarted.bind_candidate_publication_gate(lambda: enabled[0])
    assert asyncio.run(restarted.recover_issue_learning()) == 1
    assert asyncio.run(restarted.flush_candidates()) == 0
    assert len(restarted.pending_candidates) == 1

    enabled[0] = True
    assert asyncio.run(restarted.flush_candidates()) == 2
    assert restarted.pending_candidates == []
    assert len(bus.messages_on("object.rule-candidate")) == 2


def test_norns_durable_issue_operation_rejects_fingerprint_collision() -> None:
    store = InMemoryStateStore()
    norns = Norns(issue_state_store=store)

    asyncio.run(
        norns.on_typed_message(
            "object.issue",
            {
                "fingerprint": "first-fingerprint",
                "idempotency_key": "handoff:colliding-operation",
            },
        )
    )

    with pytest.raises(ValueError, match="collides with"):
        asyncio.run(
            norns.on_typed_message(
                "object.issue",
                {
                    "fingerprint": "different-fingerprint",
                    "idempotency_key": "handoff:colliding-operation",
                },
            )
        )


def test_saga_accepted_then_timeout_replay_counts_one_norns_occurrence() -> None:
    class _AcceptedThenTimeoutBus:
        def __init__(self, norns: Norns) -> None:
            self.norns = norns
            self.calls = 0

        def subscribe(self, topic, agent_name, handler):  # noqa: ANN001, ANN201
            del topic, agent_name, handler

        async def publish(self, principal, topic, payload):  # noqa: ANN001, ANN201
            assert principal == "Saga"
            assert topic == "object.issue"
            self.calls += 1
            await self.norns.on_typed_message(topic, dict(payload))
            if self.calls == 1:
                raise RuntimeError("broker acknowledgement timed out")

    store = InMemoryStateStore()
    norns = Norns(promotion_threshold=2, issue_state_store=store)
    bus = _AcceptedThenTimeoutBus(norns)
    saga = Saga(durable_state_store=store)
    saga.bind_bus(bus)
    payload = {
        "producer_principal": "Bragi",
        "id": "handoff-accepted-timeout",
        "escalation_id": "handoff-accepted-timeout",
        "correlation_id": "corr-accepted-timeout",
        "emitting_agent": "Bragi",
        "intent_category": "no_route",
        "normalized_selector": "sha256:selector",
        "failure_reason_code": "no_route",
    }

    with pytest.raises(RuntimeError, match="acknowledgement timed out"):
        asyncio.run(saga.on_typed_message("object.handoff-escalation", payload))
    asyncio.run(saga.on_typed_message("object.handoff-escalation", payload))

    fingerprint = next(iter(saga.github.issues))
    assert bus.calls == 2
    assert norns.occurrences(fingerprint) == 1
    assert norns.pending_candidates == []
    assert norns.behavior_snapshot()["issue_learning_duplicate"] == 1


# ---------------------------------------------------------------------------
# End-to-end via InMemoryBus
# ---------------------------------------------------------------------------


def test_end_to_end_handoff_flow_via_bus() -> None:
    """A handoff escalation flows through Saga -> Norns -> Mimir."""
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    saga = Saga()
    norns = Norns(promotion_threshold=3)
    mimir = Mimir()

    bus.subscribe("object.issue", "Norns", norns.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)

    fp = compute_fingerprint(
        intent_category="q",
        resource_type="r",
        normalized_selector="s",
        primary_agent="Heimdall",
        failure_reason_code="no_owned_data",
    )

    # Saga escalates three times => Norns crosses threshold, proposes candidate
    for i in range(3):
        asyncio.run(
            saga.escalate_to_github_issue(
                fingerprint=fp,
                emitting_agent="Heimdall",
                intent_category="q",
                failure_reason_code="no_owned_data",
                correlation_id=f"corr-{i}",
            )
        )
        asyncio.run(
            bus.publish(
                "Saga",
                "object.issue",
                {
                    "producer_principal": "Saga",
                    "correlation_id": f"corr-{i}",
                    "fingerprint": fp,
                },
            )
        )

    # Norns should have produced a candidate.
    assert len(norns.pending_candidates) == 1
    # Publish the candidate to Mimir via the bus (Norns as publisher).
    asyncio.run(
        bus.publish(
            "Norns",
            "object.rule-candidate",
            {
                "producer_principal": "Norns",
                "correlation_id": "corr-cand",
                **norns.pending_candidates[0],
                "target_rule_id": "auto-generated",
            },
        )
    )
    assert len(mimir.pending_candidates()) == 1

    # A brand-new rule proposed from handoff fingerprints has never run in shadow,
    # so the discovery loop stops here: promotion is refused and the catalog can
    # only change through the reviewed pull request Saga closes the issue with.
    assert mimir.promotion_ready_candidates() == ()
    with pytest.raises(ValueError, match="shadow dwell evidence is insufficient"):
        mimir.promote("auto-generated", source="handoff")
    asyncio.run(saga.close_issue(fingerprint=fp, closed_by_pr="https://example.invalid/pr/1"))
    assert saga.github.issues[fp].open is False


def test_norns_publishes_candidate_to_mimir_when_bus_bound() -> None:
    """With a bus bound, Norns is the single writer of object.rule-candidate:
    it auto-publishes each inert candidate its learners form, closing the
    Norns -> Mimir discovery loop without a manual bridge step."""
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    norns = Norns(promotion_threshold=2)
    mimir = Mimir()
    norns.bind_bus(bus)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)

    payload = {"fingerprint": "fp-loop"}
    for _ in range(2):
        asyncio.run(norns.on_typed_message("object.issue", payload))

    # Norns formed one candidate and published it; a published candidate is
    # dropped from the buffer, so pending_candidates is empty afterwards.
    assert len(norns.pending_candidates) == 0
    accepted = mimir.pending_candidates()
    assert len(accepted) == 1
    assert accepted[0]["proposed_by"] == "Norns"
    assert accepted[0]["proposal_kind"] == "new"
    assert mimir.quarantined_candidates() == ()


def test_norns_flush_is_idempotent_and_no_op_without_bus() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    # Bus-less: flush publishes nothing and does not raise.
    busless = Norns(promotion_threshold=1)
    asyncio.run(busless.on_typed_message("object.issue", {"fingerprint": "fp-a"}))
    assert len(busless.pending_candidates) == 1  # candidate formed, not published
    assert asyncio.run(busless.flush_candidates()) == 0

    # Bus bound: the candidate is published once; a re-flush republishes
    # nothing (cursor), so Mimir's flood guard never sees a duplicate.
    norns = Norns(promotion_threshold=1)
    norns.bind_bus(bus)
    asyncio.run(norns.on_typed_message("object.issue", {"fingerprint": "fp-b"}))
    assert len(bus.messages_on("object.rule-candidate")) == 1
    assert asyncio.run(norns.flush_candidates()) == 0
    assert len(bus.messages_on("object.rule-candidate")) == 1


def test_norns_throttles_candidate_publication_at_the_rate_limit() -> None:
    """Proposal publication honors the declared rate_limits (agent-pantheon
    7.9): over-budget candidates are throttled (held on the bounded buffer),
    not dropped - they flush on a later pass once the budget refills."""
    from fdai.agents._framework.rate_limiter import RateLimiter

    class _FakeClock:
        def __init__(self) -> None:
            self.t = 0.0

        def now(self) -> float:
            return self.t

    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    norns = Norns(promotion_threshold=1)
    norns.bind_bus(bus)
    clock = _FakeClock()
    # Inject a tiny, clock-controlled budget: 2 proposals/minute.
    norns._proposal_limiter = RateLimiter(per_minute=2, per_hour=100, now=clock.now)

    # Three distinct fingerprints -> three candidates; two publish and are
    # dropped from the buffer, the third is over the per-minute budget and
    # stays queued (throttled, not lost).
    for i in range(3):
        asyncio.run(norns.on_typed_message("object.issue", {"fingerprint": f"fp-{i}"}))
    assert len(norns.pending_candidates) == 1
    assert len(bus.messages_on("object.rule-candidate")) == 2
    assert norns.behavior_snapshot().get("rate_limit_exceeded") == 1

    # Budget refills after the minute window; the held candidate flushes.
    clock.t += 60.0
    assert asyncio.run(norns.flush_candidates()) == 1
    assert len(bus.messages_on("object.rule-candidate")) == 3


def test_norns_pending_buffer_drops_published_candidates() -> None:
    """Published candidates are removed from pending_candidates, so the buffer
    holds only not-yet-published proposals - bounded, with no lifetime-history
    retention (regression guard for the memory-leak fix)."""
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    norns = Norns(promotion_threshold=1)
    norns.bind_bus(bus)
    # Ten distinct candidates, all within the default 20/min budget -> every
    # one publishes and is dropped from the buffer.
    for i in range(10):
        asyncio.run(norns.on_typed_message("object.issue", {"fingerprint": f"fp-{i}"}))
    assert len(bus.messages_on("object.rule-candidate")) == 10
    assert norns.pending_candidates == []


def test_saga_escalate_publishes_object_issue_and_feeds_fingerprint_loop() -> None:
    """A bus-bound Saga publishes object.issue on escalation (it is the single
    writer of Issue), so recurring handoffs feed Norns' fingerprint learner
    end to end - no manual bridge step - and Mimir accepts the new-rule
    candidate."""
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    saga = Saga()
    saga.bind_bus(bus)
    norns = Norns(promotion_threshold=2)
    norns.bind_bus(bus)
    mimir = Mimir()
    bus.subscribe("object.issue", "Norns", norns.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)

    fp = compute_fingerprint(
        intent_category="q",
        resource_type="r",
        normalized_selector="s",
        primary_agent="Heimdall",
        failure_reason_code="no_owned_data",
    )
    for i in range(2):
        asyncio.run(
            saga.escalate_to_github_issue(
                fingerprint=fp,
                emitting_agent="Heimdall",
                intent_category="q",
                failure_reason_code="no_owned_data",
                correlation_id=f"c-{i}",
            )
        )
    # Saga auto-published object.issue twice -> Norns crossed its threshold and
    # proposed a new-rule candidate -> Mimir's guard accepted it.
    assert len(bus.messages_on("object.issue")) == 2
    assert norns.occurrences(fp) == 2
    accepted = mimir.pending_candidates()
    assert len(accepted) == 1
    assert accepted[0]["proposal_kind"] == "new"


# ---------------------------------------------------------------------------
# Norns - outcome-threshold learner (rubric C2 / #22)
# ---------------------------------------------------------------------------


def _run_outcomes(norns: Norns, target: str, *, rollbacks: int, successes: int) -> None:
    for _ in range(rollbacks):
        asyncio.run(
            norns.on_typed_message(
                "object.audit-entry", {"action_type": target, "result": "rollback"}
            )
        )
    for _ in range(successes):
        asyncio.run(
            norns.on_typed_message(
                "object.audit-entry", {"action_type": target, "result": "success"}
            )
        )


def test_norns_proposes_threshold_adjustment_on_high_rollback() -> None:
    norns = Norns(min_outcome_samples=10, rollback_alarm_rate=0.2)
    # 4 rollbacks / 10 total = 0.4 > 0.2 alarm.
    _run_outcomes(norns, "remediate.resize-vm-up", rollbacks=4, successes=6)
    proposals = [
        c for c in norns.pending_candidates if c["proposal_kind"] == "threshold_adjustment"
    ]
    assert len(proposals) == 1
    ev = proposals[0]["evidence"]
    assert ev["target"] == "remediate.resize-vm-up"
    assert ev["sample_size"] == 10
    assert ev["rollback_rate"] == 0.4
    assert proposals[0]["suggested_change"] == "raise_confidence_threshold"


def test_norns_no_threshold_proposal_below_min_samples() -> None:
    norns = Norns(min_outcome_samples=20, rollback_alarm_rate=0.2)
    _run_outcomes(norns, "remediate.x", rollbacks=3, successes=2)  # 5 < 20
    assert norns.pending_candidates == []
    assert norns.outcome_rate("remediate.x") == 0.6


def test_norns_no_threshold_proposal_when_rollback_low() -> None:
    norns = Norns(min_outcome_samples=10, rollback_alarm_rate=0.2)
    _run_outcomes(norns, "remediate.safe", rollbacks=1, successes=19)  # 0.05 < 0.2
    assert norns.pending_candidates == []


def test_norns_threshold_proposal_dedups() -> None:
    norns = Norns(min_outcome_samples=10, rollback_alarm_rate=0.2)
    _run_outcomes(norns, "remediate.y", rollbacks=5, successes=5)
    _run_outcomes(norns, "remediate.y", rollbacks=5, successes=5)  # keep firing
    proposals = [
        c for c in norns.pending_candidates if c["proposal_kind"] == "threshold_adjustment"
    ]
    assert len(proposals) == 1  # proposed once, then deduped


# ---------------------------------------------------------------------------
# Norns - override learner (rubric C2 / #22)
# ---------------------------------------------------------------------------


def test_norns_proposes_retirement_on_recurring_disable_override() -> None:
    norns = Norns(override_retire_threshold=3)
    for _ in range(3):
        norns.observe_override(
            {"rule_id": "net.public.deny", "mode": "disabled", "event": "create"},
        )
    proposals = [c for c in norns.pending_candidates if c["proposal_kind"] == "retirement"]
    assert len(proposals) == 1
    assert proposals[0]["target_rule_id"] == "net.public.deny"
    assert norns.override_count("net.public.deny") == 3


def test_norns_proposes_revision_on_recurring_downgrade_override() -> None:
    norns = Norns(override_retire_threshold=3)
    for _ in range(3):
        norns.observe_override(
            {"rule_id": "disk.encrypt", "mode": "severity-downgrade", "event": "create"},
        )
    proposals = [c for c in norns.pending_candidates if c["proposal_kind"] == "revision"]
    assert len(proposals) == 1
    assert proposals[0]["target_rule_id"] == "disk.encrypt"


def test_norns_override_below_threshold_no_proposal() -> None:
    norns = Norns(override_retire_threshold=5)
    for _ in range(4):
        norns.observe_override({"rule_id": "r1", "mode": "disabled", "event": "create"})
    assert norns.pending_candidates == []


# ---------------------------------------------------------------------------
# Norns - approval-pattern learner
# ---------------------------------------------------------------------------


def test_norns_proposes_revision_after_recurring_rejections() -> None:
    """Recurring HIL rejections of one action type propose a revision (the safe,
    autonomy-lowering direction) - humans consistently refuse it."""
    norns = Norns(rejection_revise_threshold=3)
    for i in range(3):
        asyncio.run(
            norns.on_typed_message(
                "object.approval",
                {
                    "action_type": "remediate.enable-encryption",
                    "state": "rejected",
                    "correlation_id": f"c-{i}",
                },
            )
        )
    proposals = [
        c for c in norns.pending_candidates if c["source_signal"] == "recurring_hil_rejection"
    ]
    assert len(proposals) == 1
    assert proposals[0]["proposal_kind"] == "revision"
    assert proposals[0]["target_rule_id"] == "remediate.enable-encryption"
    assert proposals[0]["evidence"]["rejection_count"] == 3
    assert norns.rejection_count("remediate.enable-encryption") == 3


def test_norns_approvals_alone_propose_nothing() -> None:
    """Approvals are counted for evidence only; the learner never proposes an
    auto-promotion (the risky direction)."""
    norns = Norns(rejection_revise_threshold=2)
    for i in range(5):
        asyncio.run(
            norns.on_typed_message(
                "object.approval",
                {
                    "action_type": "ops.restart-service",
                    "state": "approved",
                    "correlation_id": f"a-{i}",
                },
            )
        )
    assert norns.pending_candidates == []
    assert norns.rejection_count("ops.restart-service") == 0


def test_norns_dedups_approval_per_correlation() -> None:
    """A re-delivered decision (at-least-once) is scored once; only a distinct
    correlation advances the rejection count."""
    norns = Norns(rejection_revise_threshold=2)
    for _ in range(2):
        asyncio.run(
            norns.on_typed_message(
                "object.approval",
                {
                    "action_type": "remediate.delete-storage",
                    "state": "rejected",
                    "correlation_id": "dup",
                },
            )
        )
    assert norns.rejection_count("remediate.delete-storage") == 1
    assert norns.pending_candidates == []  # threshold 2 not reached (deduped)
    asyncio.run(
        norns.on_typed_message(
            "object.approval",
            {
                "action_type": "remediate.delete-storage",
                "state": "rejected",
                "correlation_id": "distinct",
            },
        )
    )
    assert norns.rejection_count("remediate.delete-storage") == 2
    proposals = [
        c for c in norns.pending_candidates if c["source_signal"] == "recurring_hil_rejection"
    ]
    assert len(proposals) == 1


def test_norns_fingerprint_learner_still_isolated() -> None:
    """Outcome/override learners do not perturb the fingerprint learner."""
    norns = Norns(promotion_threshold=3)
    for _ in range(3):
        asyncio.run(norns.on_typed_message("object.issue", {"fingerprint": "fp-x"}))
    asyncio.run(
        norns.on_typed_message("object.audit-entry", {"action_type": "a", "result": "success"})
    )
    new_rules = [c for c in norns.pending_candidates if c["proposal_kind"] == "new"]
    assert len(new_rules) == 1


def test_norns_outcome_learner_normalizes_action_run_state() -> None:
    """An audit-entry that carries Thor's raw ``state`` (not a normalized
    ``result``) still scores: rolled_back / failed -> adverse, succeeded ->
    success."""
    norns = Norns(min_outcome_samples=10, rollback_alarm_rate=0.2)
    for _ in range(4):
        asyncio.run(
            norns.on_typed_message(
                "object.audit-entry", {"action_type": "remediate.z", "state": "rolled_back"}
            )
        )
    for _ in range(6):
        asyncio.run(
            norns.on_typed_message(
                "object.audit-entry", {"action_type": "remediate.z", "state": "succeeded"}
            )
        )
    proposals = [
        c for c in norns.pending_candidates if c["proposal_kind"] == "threshold_adjustment"
    ]
    assert len(proposals) == 1
    assert proposals[0]["evidence"]["rollback_rate"] == 0.4


def test_norns_counts_distinct_action_targets_under_one_correlation() -> None:
    norns = Norns(min_outcome_samples=1, rollback_alarm_rate=0.0)
    for action_type in ("remediate.a", "remediate.b"):
        asyncio.run(
            norns.on_typed_message(
                "object.audit-entry",
                {
                    "action_type": action_type,
                    "state": "rolled_back",
                    "correlation_id": "shared-correlation",
                },
            )
        )
    assert norns._outcomes == {  # noqa: SLF001 - dedup boundary assertion
        "remediate.a": {"success": 0, "rollback": 1},
        "remediate.b": {"success": 0, "rollback": 1},
    }
    assert len(norns._counted_correlations) == 2  # noqa: SLF001


# ---------------------------------------------------------------------------
# Discovery loop B: Saga republishes outcomes -> Norns learns
# ---------------------------------------------------------------------------


def _saga_on_bus() -> tuple[Saga, InMemoryBus]:
    bus = InMemoryBus(registry=load_pantheon())
    saga = Saga()
    saga.bind_bus(bus)
    return saga, bus


def test_saga_republishes_terminal_action_outcome() -> None:
    saga, bus = _saga_on_bus()
    for state, expected in (
        ("succeeded", "success"),
        ("failed", "failure"),
        ("rolled_back", "rollback"),
    ):
        bus.clear_history()
        asyncio.run(
            saga.on_typed_message(
                "object.action-run",
                {"action_type": "remediate.z", "state": state, "correlation_id": "c"},
            )
        )
        entries = bus.messages_on("object.audit-entry")
        assert len(entries) == 1
        assert entries[0].payload["result"] == expected
        assert entries[0].payload["action_type"] == "remediate.z"


def test_saga_prefers_direct_result_over_unmappable_state() -> None:
    """Consistency with Norns (which reads ``result`` before ``state``): a
    producer that stamped a canonical ``result`` but a ``state`` Saga cannot
    map is still republished, using the direct result. Without this the writer
    (Saga) would drop a record the reader (Norns) would have learned."""
    saga, bus = _saga_on_bus()
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {
                "action_type": "remediate.z",
                "result": "rollback",
                "state": "some_future_state",
                "correlation_id": "c",
            },
        )
    )
    entries = bus.messages_on("object.audit-entry")
    assert len(entries) == 1
    assert entries[0].payload["result"] == "rollback"


def test_saga_ignores_non_canonical_direct_result() -> None:
    """A junk ``result`` does not bypass the ``state`` mapping: Saga only
    honors a directly-stamped result when it is in the canonical vocabulary,
    so an audit-entry always carries a clean value."""
    saga, bus = _saga_on_bus()
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {
                "action_type": "remediate.z",
                "result": "banana",
                "state": "succeeded",
                "correlation_id": "c",
            },
        )
    )
    entries = bus.messages_on("object.audit-entry")
    assert len(entries) == 1
    assert entries[0].payload["result"] == "success"


def test_saga_does_not_republish_intermediate_or_untyped_state() -> None:
    saga, bus = _saga_on_bus()
    # Intermediate state -> no learnable outcome -> no audit-entry.
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {"action_type": "remediate.z", "state": "executing", "correlation_id": "c"},
        )
    )
    # Terminal but no action_type -> nothing to attribute.
    asyncio.run(
        saga.on_typed_message("object.action-run", {"state": "succeeded", "correlation_id": "c"})
    )
    assert bus.messages_on("object.audit-entry") == []


def test_saga_skips_republish_on_empty_correlation() -> None:
    """An empty correlation would give the audit-entry an empty partition key
    (ordering loss) and Norns cannot dedup it - skip the republish."""
    saga, bus = _saga_on_bus()
    asyncio.run(
        saga.on_typed_message(
            "object.action-run", {"action_type": "a", "state": "failed", "correlation_id": ""}
        )
    )
    assert bus.messages_on("object.audit-entry") == []


def test_saga_self_loop_guard_skips_already_republished_record() -> None:
    """Defensive: a record already carrying audited_topic is never
    re-republished, so an audit-of-an-audit loop cannot form even if Saga is
    wired to consume object.audit-entry later."""
    saga, bus = _saga_on_bus()
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {
                "action_type": "a",
                "state": "failed",
                "correlation_id": "c",
                "audited_topic": "object.action-run",
            },
        )
    )
    assert bus.messages_on("object.audit-entry") == []


def test_saga_republishes_shadow_flag() -> None:
    saga, bus = _saga_on_bus()
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {"action_type": "a", "state": "succeeded", "correlation_id": "c", "shadow_mode": True},
        )
    )
    entries = bus.messages_on("object.audit-entry")
    assert len(entries) == 1
    assert entries[0].payload["shadow_mode"] is True


def test_norns_skips_shadow_outcomes() -> None:
    """A shadow 'success' is judged-and-logged, not a real execution - it MUST
    NOT be learned from (it would dilute the real rollback rate)."""
    norns = Norns(min_outcome_samples=1, rollback_alarm_rate=0.0)
    # A shadow rollback that would otherwise trip the alarm -> ignored.
    asyncio.run(
        norns.on_typed_message(
            "object.audit-entry",
            {"action_type": "a", "result": "rollback", "correlation_id": "c", "shadow_mode": True},
        )
    )
    assert norns.pending_candidates == []
    # A real (non-shadow) rollback IS learned.
    asyncio.run(
        norns.on_typed_message(
            "object.audit-entry",
            {"action_type": "a", "result": "rollback", "correlation_id": "d"},
        )
    )
    assert any(c["proposal_kind"] == "threshold_adjustment" for c in norns.pending_candidates)


def test_saga_audit_entry_drives_norns_outcome_learning() -> None:
    """End to end: Saga republishes terminal outcomes, Norns (subscribed to
    object.audit-entry) scores the rollback rate and proposes a threshold
    adjustment - the closed discovery loop."""
    saga, bus = _saga_on_bus()
    norns = Norns(min_outcome_samples=10, rollback_alarm_rate=0.2)
    bus.subscribe("object.audit-entry", "Norns", norns.on_typed_message)

    # 4 failed actions - each emits FAILED then ROLLED_BACK (2 audit-entries,
    # same correlation) -> deduped to 1 adverse each. 6 succeeded.
    for i in range(4):
        for state in ("failed", "rolled_back"):
            asyncio.run(
                saga.on_typed_message(
                    "object.action-run",
                    {"action_type": "remediate.z", "state": state, "correlation_id": f"f{i}"},
                )
            )
    for i in range(6):
        asyncio.run(
            saga.on_typed_message(
                "object.action-run",
                {"action_type": "remediate.z", "state": "succeeded", "correlation_id": f"s{i}"},
            )
        )

    proposals = [
        c for c in norns.pending_candidates if c["proposal_kind"] == "threshold_adjustment"
    ]
    assert len(proposals) == 1
    assert proposals[0]["evidence"]["sample_size"] == 10  # dedup: 4 adverse + 6 success
    assert proposals[0]["evidence"]["rollback_rate"] == 0.4


def test_norns_dedups_outcome_per_correlation() -> None:
    """A single action that emits FAILED then ROLLED_BACK is scored once."""
    norns = Norns()
    # One failed action: FAILED + ROLLED_BACK, same correlation -> 1 adverse.
    for result in ("failure", "rollback"):
        asyncio.run(
            norns.on_typed_message(
                "object.audit-entry",
                {"action_type": "a", "result": result, "correlation_id": "same"},
            )
        )
    # One success, distinct correlation.
    asyncio.run(
        norns.on_typed_message(
            "object.audit-entry",
            {"action_type": "a", "result": "success", "correlation_id": "other"},
        )
    )
    # Deduped: 1 adverse + 1 success = 0.5 rollback rate (NOT 2 adverse / 3 = 0.67).
    assert norns.outcome_rate("a") == 0.5


def test_norns_constructor_rejects_misconfiguration() -> None:
    """Out-of-range config would make the learner propose on thin evidence."""
    with pytest.raises(ValueError, match="promotion_threshold"):
        Norns(promotion_threshold=0)
    with pytest.raises(ValueError, match="rollback_alarm_rate"):
        Norns(rollback_alarm_rate=1.5)
    with pytest.raises(ValueError, match="min_outcome_samples"):
        Norns(min_outcome_samples=0)
    with pytest.raises(ValueError, match="override_retire_threshold"):
        Norns(override_retire_threshold=0)
