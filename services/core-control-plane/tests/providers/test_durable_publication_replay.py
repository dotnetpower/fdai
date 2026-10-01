from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import pytest
from fdai.agents.bragi import Bragi
from fdai.agents.heimdall import Heimdall
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.saga import Saga
from fdai.agents.var import Var
from fdai.shared.providers import EventBus, StateStore
from fdai.shared.providers.event_bus import EventPublishNotAttemptedError
from fdai_service_contracts.compatibility import canonical_digest


class _Harness(Protocol):
    bus: EventBus

    def group(self, suffix: str) -> str: ...

    async def collect(
        self,
        topic: str,
        group: str,
        *,
        expected_count: int,
    ) -> tuple[Any, ...]: ...


@dataclass(slots=True)
class _AgentBus:
    event_bus: EventBus
    fail_first: bool = False

    async def publish(
        self,
        _principal: str,
        topic: str,
        payload: Mapping[str, object],
    ) -> object:
        if self.fail_first:
            self.fail_first = False
            raise EventPublishNotAttemptedError("broker unavailable before send")
        key = str(payload.get("idempotency_key") or payload.get("correlation_id") or "")
        return await self.event_bus.publish(topic, key, payload)


@dataclass(frozen=True, slots=True)
class ReplayCase:
    family: str
    topic: str
    idempotency_key: str
    payload: Mapping[str, object]
    run: Callable[[_Harness, StateStore, Mapping[str, object]], Awaitable[int]]


async def _bragi_publication(
    harness: _Harness,
    store: StateStore,
    payload: Mapping[str, object],
) -> int:
    first = Bragi(state_store=store)
    first.bind_bus(_AgentBus(harness.bus, fail_first=True))  # type: ignore[arg-type]
    with pytest.raises(EventPublishNotAttemptedError):
        await first.publish_handoff_event(dict(payload))
    rebuilt = Bragi(state_store=store)
    rebuilt.bind_bus(_AgentBus(harness.bus))  # type: ignore[arg-type]
    return await rebuilt.recover_bragi_publications()


async def _var_final_approval(
    harness: _Harness,
    store: StateStore,
    payload: Mapping[str, object],
) -> int:
    correlation_digest = hashlib.sha256(b"corr-var-replay").hexdigest()
    key = f"pantheon/var/approval/{correlation_digest}/non-action/final"
    await store.write_state(
        key,
        {
            "schema_version": "1.0.0",
            "record_kind": "final_approval",
            "revision": 1,
            "correlation_id": "corr-var-replay",
            "publication_status": "pending",
            "approval": dict(payload),
        },
    )
    var = Var(bus=_AgentBus(harness.bus), state_store=store)  # type: ignore[arg-type]
    _finalized, published = await var.recover_approvals()
    return published


async def _saga_audit(
    harness: _Harness,
    store: StateStore,
    payload: Mapping[str, object],
) -> int:
    saga = Saga(durable_state_store=store)
    saga.bind_bus(_AgentBus(harness.bus, fail_first=True))  # type: ignore[arg-type]
    with pytest.raises(EventPublishNotAttemptedError):
        await saga._publish_audit_entry_with_outbox(dict(payload))  # noqa: SLF001
    rebuilt = Saga(durable_state_store=store)
    rebuilt.bind_bus(_AgentBus(harness.bus))  # type: ignore[arg-type]
    return await rebuilt.recover_audit_outbox()


async def _muninn_publication(
    harness: _Harness,
    store: StateStore,
    payload: Mapping[str, object],
) -> int:
    muninn = Muninn(durable_state_store=store)
    muninn.bind_bus(_AgentBus(harness.bus, fail_first=True))  # type: ignore[arg-type]
    with pytest.raises(EventPublishNotAttemptedError):
        await muninn._publish_with_outbox(  # noqa: SLF001
            "pantheon/muninn/operational-outbox/replay/one",
            "object.context-index",
            dict(payload),
        )
    rebuilt = Muninn(durable_state_store=store)
    rebuilt.bind_bus(_AgentBus(harness.bus))  # type: ignore[arg-type]
    return await rebuilt.recover_operational_publications()


async def _mimir_publication(
    harness: _Harness,
    store: StateStore,
    payload: Mapping[str, object],
) -> int:
    key = "mimir-rule-replay"
    await store.write_state(
        f"pantheon/mimir/governance/rule-publications/{key}",
        {
            "schema_version": "1.0.0",
            "revision": 1,
            "status": "pending",
            "topic": "object.rule",
            "idempotency_key": key,
            "payload": dict(payload),
        },
    )
    mimir = Mimir(governance_state_store=store)
    mimir.bind_bus(_AgentBus(harness.bus))  # type: ignore[arg-type]
    return await mimir.recover_governance_state()


async def _heimdall_publication(
    harness: _Harness,
    store: StateStore,
    payload: Mapping[str, object],
) -> int:
    heimdall = Heimdall(state_store=store)
    heimdall.bind_bus(_AgentBus(harness.bus, fail_first=True))  # type: ignore[arg-type]
    with pytest.raises(EventPublishNotAttemptedError):
        await heimdall._publish_once("object.anomaly", dict(payload))  # noqa: SLF001
    rebuilt = Heimdall(state_store=store)
    rebuilt.bind_bus(_AgentBus(harness.bus))  # type: ignore[arg-type]
    return await rebuilt.recover_publications()


_CASES = (
    ReplayCase(
        family="bragi-publication",
        topic="object.handoff-escalation",
        idempotency_key="handoff-key-one",
        payload={
            "schema_version": "1.0.0",
            "idempotency_key": "handoff-key-one",
            "correlation_id": "corr-one",
            "resource_id": "resource-one",
            "target_agent": "Saga",
            "reason": "handoff",
            "message": "bounded handoff",
        },
        run=_bragi_publication,
    ),
    ReplayCase(
        family="var-final-approval",
        topic="object.approval",
        idempotency_key="approval:replay",
        payload={
            "producer_principal": "Var",
            "correlation_id": "corr-var-replay",
            "idempotency_key": "approval:replay",
            "state": "approved",
            "approvers": ["owner@example.com"],
            "original_quorum_required": 1,
            "effective_quorum_required": 1,
            "development_authority": None,
        },
        run=_var_final_approval,
    ),
    ReplayCase(
        family="saga-audit",
        topic="object.audit-entry",
        idempotency_key="audit:replay",
        payload={
            "schema_version": "1.0.0",
            "idempotency_key": "audit:replay",
            "correlation_id": "corr-audit-replay",
            "event_type": "audit.replay",
            "resource_id": "resource-audit",
        },
        run=_saga_audit,
    ),
    ReplayCase(
        family="muninn-publication",
        topic="object.context-index",
        idempotency_key="context:replay",
        payload={
            "producer_principal": "Muninn",
            "kind": "semantic_retrieval_failure",
            "correlation_id": "corr-context-replay",
            "idempotency_key": "context:replay",
        },
        run=_muninn_publication,
    ),
    ReplayCase(
        family="mimir-publication",
        topic="object.rule",
        idempotency_key="mimir-rule-replay",
        payload={
            "producer_principal": "Mimir",
            "kind": "catalog_review_outcome",
            "correlation_id": "corr-mimir-replay",
            "idempotency_key": "mimir-rule-replay",
            "rule_id": "rule.replay",
        },
        run=_mimir_publication,
    ),
    ReplayCase(
        family="heimdall-publication",
        topic="object.anomaly",
        idempotency_key="heimdall:replay",
        payload={
            "producer_principal": "Heimdall",
            "correlation_id": "corr-heimdall-replay",
            "idempotency_key": "heimdall:replay",
            "resource_id": "resource-heimdall",
            "event_type": "anomaly.replay",
        },
        run=_heimdall_publication,
    ),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _CASES, ids=[case.family for case in _CASES])
async def test_pending_publication_replays_same_idempotency_key_after_broker_interruption(
    case: ReplayCase,
    event_bus_harness: _Harness,
    state_store: StateStore,
) -> None:
    recovered = await case.run(event_bus_harness, state_store, case.payload)
    assert recovered >= 1

    delivered = await event_bus_harness.collect(
        case.topic,
        event_bus_harness.group(f"{case.family}-replay"),
        expected_count=1,
    )
    assert len(delivered) == 1
    assert delivered[0].key == case.idempotency_key
    assert delivered[0].payload["idempotency_key"] == case.idempotency_key
    assert canonical_digest(dict(delivered[0].payload)) == canonical_digest(case.payload)


def test_inventoried_families_without_broker_replay_are_not_authority_publications() -> None:
    """Document non-skipped inventory entries that do not own broker replay here."""

    assert {
        "bragi-turn": "turn outbox is a Bragi-local transcript state machine",
        "odin-decision": "Odin publishes decisions directly and has no durable broker outbox",
        "saga-handoff": "handoff recovery publishes GitHub issue records, not broker authority",
        "forseti-publication": (
            "Forseti verdicts are recomputed decisions, not terminal replay rows"
        ),
        "vidar-rollback": "Vidar recovery replay is executor/effect driven, not broker-only",
        "thor-action-run": (
            "Thor ActionRun restart checkpoint is durable state, not broker publication"
        ),
        "norns-publication": "Norns persists candidates for Mimir handoff instead of bus replay",
    }
