from __future__ import annotations

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.mimir_constants import _RULE_PUBLICATION_PREFIX
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.mimir import Mimir
from fdai.core.operational_context.test_context_commands import (
    TestContextCommandHandler as _TestContextCommandHandler,
)
from fdai.core.operational_context.test_context_lifecycle import GovernedTestContextStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.core.operational_context.test_test_context import NOW, _claim, _TransitionAdmission


class _FailOncePolicyBus(InMemoryBus):
    def __init__(self) -> None:
        super().__init__(registry=load_pantheon())
        self.failed = False

    async def publish(self, principal: str, topic: str, payload: dict[str, object]) -> None:
        if topic == "object.policy" and not self.failed:
            self.failed = True
            raise RuntimeError("broker unavailable")
        await super().publish(principal, topic, payload)


def _proposal_payload() -> dict[str, object]:
    claim = _claim()
    return {
        "producer_principal": "Huginn",
        "event_type": "test_context.command.v1",
        "correlation_id": "context-example",
        "idempotency_key": "context-example",
        "attributes": {
            "request": {
                "operation": "propose",
                "context_id": claim.context_id,
                "access_scope_digest": claim.access_scope_digest,
                "target_ref": claim.target_ref,
                "signal_code": claim.signal_code,
                "expected_revision": 0,
                "policy_revision": claim.policy_revision,
                "source_ref": claim.source_ref,
                "semantic_receipt": "sha256:" + "a" * 64,
                "expected_min": 60,
                "expected_max": 90,
                "effective_from": NOW.isoformat(),
                "effective_to": claim.effective_to.isoformat(),
            },
            "actor_id": "operator-one",
            "actor_roles": ["Contributor"],
            "idempotency_key": "context-example",
            "requested_at": NOW.isoformat(),
        },
    }


async def test_mimir_test_context_policy_uses_outbox_after_applied_transition() -> None:
    context_store = InMemoryStateStore()
    governance_store = InMemoryStateStore()
    admission = _TransitionAdmission()
    handler = _TestContextCommandHandler(
        contexts=GovernedTestContextStore(
            store=context_store,
            admission=admission,
            clock=lambda: NOW,
        ),
        admission=admission,
        clock=lambda: NOW,
    )
    first = Mimir(governance_state_store=governance_store, clock=lambda: NOW)
    first.bind_test_context_commands(handler)
    first.bind_bus(_FailOncePolicyBus())
    payload = _proposal_payload()

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await first.on_typed_message("object.event", payload)

    rows, _total = await governance_store.read_state_page(
        f"{_RULE_PUBLICATION_PREFIX}/",
        limit=10,
        field="status",
        value="pending",
    )
    assert len(rows) == 1
    original_key = rows[0]["idempotency_key"]
    bus = InMemoryBus(registry=load_pantheon())
    restarted = Mimir(governance_state_store=governance_store, clock=lambda: NOW)
    restarted.bind_test_context_commands(handler)
    restarted.bind_bus(bus)

    assert await restarted.recover_governance_state() == 1
    assert len(bus.messages_on("object.policy")) == 1
    assert bus.messages_on("object.policy")[0].payload["idempotency_key"] == original_key

    await restarted.on_typed_message("object.event", payload)

    assert len(bus.messages_on("object.policy")) == 1
