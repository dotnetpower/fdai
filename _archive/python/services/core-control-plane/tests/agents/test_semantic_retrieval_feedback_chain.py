from __future__ import annotations

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.delivery.persistence import StateStoreSemanticFeedbackCandidateStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_QUERY = "sha256:" + "a" * 64
_SCOPE = "sha256:" + "b" * 64
_CATALOG = "sha256:" + "c" * 64


def _raw_event() -> dict[str, object]:
    return {
        "idempotency_key": "retrieval-validation:attempt-1",
        "event_id": "retrieval-validation:attempt-1",
        "event_type": "catalog.semantic_retrieval_failure.validated",
        "correlation_id": "attempt:semantic:1",
        "source": "retrieval-evaluation",
        "resource_id": "catalog:active",
        "resource_type": "rule-catalog",
        "attributes": {
            "failure": {
                "attempt_id": "attempt:semantic:1",
                "query_digest": _QUERY,
                "principal_scope_digest": _SCOPE,
                "catalog_digest": _CATALOG,
                "reason_code": "target-not-retrieved",
                "layer": "ranking_error",
                "reproduced": True,
                "evidence_refs": ["receipt:retrieval:1", "receipt:validation:1"],
                "exact_target_rule_ref": ("rule:object-storage.public-access.deny@1.0.0"),
            }
        },
    }


async def test_reproduced_failure_flows_once_through_owned_topics() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    state = InMemoryStateStore()
    huginn = Huginn(bus=bus)
    heimdall = Heimdall(bus=bus)
    muninn = Muninn()
    muninn.bind_bus(bus)
    saga = Saga()
    saga.bind_bus(bus)
    norns = Norns(semantic_feedback_store=StateStoreSemanticFeedbackCandidateStore(state))
    norns.bind_bus(bus)
    mimir = Mimir()
    mimir.bind_bus(bus)
    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    bus.subscribe("object.retrieval-validation", "Muninn", muninn.on_typed_message)
    bus.subscribe("object.retrieval-validation", "Saga", saga.on_typed_message)
    bus.subscribe("object.context-index", "Norns", norns.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)

    assert await huginn.ingest(_raw_event()) is not None
    assert await huginn.ingest(_raw_event()) is None

    validations = bus.messages_on("object.retrieval-validation")
    contexts = bus.messages_on("object.context-index")
    proposals = bus.messages_on("object.rule-candidate")
    assert [message.principal for message in validations] == ["Heimdall"]
    assert [message.principal for message in contexts] == ["Muninn"]
    assert [message.principal for message in proposals] == ["Norns"]
    assert validations[0].payload["idempotency_key"].startswith("retrieval-validation:")
    assert contexts[0].payload["idempotency_key"].startswith("semantic-feedback:")
    assert len(saga.audit_chain.entries) == 1
    assert saga.audit_chain.entries[0].topic == "object.retrieval-validation"
    assert len(state.audit_entries) == 1
    assert state.audit_entries[0]["entry"]["promotion_applied"] is False
    assert mimir.pending_candidates()[0]["source_signal"] == "semantic_retrieval_failure"
