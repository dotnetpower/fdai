from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.forseti import Forseti, _rule_revision, _rule_state_is_newer, _rule_updated_at
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_OBSERVED = "2026-10-01T00:00:00+00:00"
_NEWER = "2026-10-01T00:05:00+00:00"
_OLDER = "2026-10-01T00:00:00+00:00"
_RESOURCE = "resource-cross-vertical"


class _RequestFailingBus(InMemoryBus):
    async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.arbitration-request":
            raise RuntimeError("simulated arbitration request outage")
        await super().publish(principal, topic, payload)


def _cost_payload(correlation_id: str, observed_at: str = _OBSERVED) -> dict[str, Any]:
    return {
        "producer_principal": "Njord",
        "correlation_id": correlation_id,
        "idempotency_key": f"{correlation_id}:cost",
        "resource_id": _RESOURCE,
        "recommendation": "scale_down",
        "impact": 0.7,
        "observed_at": observed_at,
        "source_freshness": [
            {
                "source": "cost",
                "observed_at": observed_at,
                "max_age_seconds": 300,
            }
        ],
    }


def _capacity_payload(correlation_id: str, observed_at: str = _OBSERVED) -> dict[str, Any]:
    return {
        "producer_principal": "Freyr",
        "correlation_id": correlation_id,
        "idempotency_key": f"{correlation_id}:capacity",
        "resource_id": _RESOURCE,
        "recommendation": "scale_up",
        "impact": 0.9,
        "observed_at": observed_at,
        "source_freshness": [
            {
                "source": "capacity",
                "observed_at": observed_at,
                "max_age_seconds": 120,
            }
        ],
    }


async def _publish_domain_conflict(
    forseti: Forseti,
    *,
    cost_correlation: str = "corr-cost",
    capacity_correlation: str = "corr-capacity",
    observed_at: str = _OBSERVED,
) -> None:
    await forseti.on_typed_message(
        "object.cost-anomaly", _cost_payload(cost_correlation, observed_at)
    )
    await forseti.on_typed_message(
        "object.capacity-forecast", _capacity_payload(capacity_correlation, observed_at)
    )


async def _run_runtime_until(
    runtime: PantheonRuntime,
    predicate: Callable[[], bool],
    *,
    steps: int = 2000,
) -> None:
    task = asyncio.create_task(runtime.run())
    try:
        for _ in range(steps):
            await asyncio.sleep(0)
            if predicate():
                return
        raise AssertionError("runtime condition was not observed")
    finally:
        await runtime.stop()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup path
            pass


def _provider_payloads(provider: LocalEventBus, topic: str) -> list[dict[str, Any]]:
    return [dict(payload) for _key, payload in provider._records.get(topic, [])]


def test_domain_signal_join_requires_same_cutoff_and_preserves_source_lineage() -> None:
    stale_bus = InMemoryBus(load_pantheon())
    stale_forseti = Forseti(bus=stale_bus)

    async def _stale() -> None:
        await stale_forseti.on_typed_message(
            "object.capacity-forecast", _capacity_payload("corr-newer", _NEWER)
        )
        await stale_forseti.on_typed_message(
            "object.cost-anomaly", _cost_payload("corr-older", _OLDER)
        )

    asyncio.run(_stale())

    assert stale_bus.messages_on("object.arbitration-request") == []
    assert stale_forseti.behavior_snapshot()["domain_advice:stale"] == 1

    bus = InMemoryBus(load_pantheon())
    forseti = Forseti(bus=bus)
    asyncio.run(_publish_domain_conflict(forseti))

    (request,) = bus.messages_on("object.arbitration-request")
    assert request.payload["source_correlations"] == {
        "cost": "corr-cost",
        "capacity": "corr-capacity",
    }
    assert request.payload["domain_observed_at"] == {
        "cost": _OBSERVED,
        "capacity": _OBSERVED,
    }
    assert {item["source"] for item in request.payload["domain_source_freshness"]["cost"]} == {
        "cost"
    }
    assert {item["source"] for item in request.payload["domain_source_freshness"]["capacity"]} == {
        "capacity"
    }


def test_publish_failure_still_closes_odin_down_as_audited_non_action_verdict() -> None:
    bus = _RequestFailingBus(load_pantheon())
    saga = Saga()
    thor = Thor(bus=bus)
    forseti = Forseti(bus=bus, agent_availability=lambda: ("Odin",))
    bus.subscribe("object.verdict", "Saga", saga.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.action-run", "Saga", saga.on_typed_message)

    asyncio.run(_publish_domain_conflict(forseti, cost_correlation="corr-down"))

    (verdict,) = bus.messages_on("object.verdict")
    assert verdict.payload["reason"] == "arbitration_owner_unavailable"
    assert verdict.payload["action_type"] == ""
    assert verdict.payload["arbitration"]["arbitration_request"]["domains_in_conflict"] == [
        "capacity",
        "cost",
    ]
    assert bus.messages_on("object.action-run") == []
    assert thor.behavior_snapshot()["non_action_verdict_ignored"] == 1
    replay = saga.replay_for_correlation("corr-capacity")
    assert replay
    assert replay[0].topic == "object.verdict"
    assert verdict.payload["arbitration"]["arbitration_request"]["source_correlations"] == {
        "cost": "corr-down",
        "capacity": "corr-capacity",
    }


def test_advisory_verdicts_use_typed_stable_idempotency_keys() -> None:
    bus = InMemoryBus(load_pantheon())
    forseti = Forseti(bus=bus)

    async def _drive() -> None:
        await forseti._publish_learned_output_advisory(  # noqa: SLF001 - regression seam
            {
                "correlation_id": "corr-advisory",
                "idempotency_key": "forecast-input-key",
                "resource_id": _RESOURCE,
            },
            advisory_source="forecast",
        )
        forseti._advisory_arbitrations.set(  # noqa: SLF001 - regression seam
            "corr-advisory",
            {
                "source": "capacity_forecast",
                "published": False,
                "lock": asyncio.Lock(),
            },
        )
        forseti._arbitration_resources.set("corr-advisory", _RESOURCE)  # noqa: SLF001
        await forseti._settle_advisory_arbitration(  # noqa: SLF001 - regression seam
            "corr-advisory",
            {"winning_domain": "capacity", "losing_domains": ["cost"], "margin": 0.1},
            outcome="resolved",
        )

    asyncio.run(_drive())

    keys = [message.payload["idempotency_key"] for message in bus.messages_on("object.verdict")]
    assert len(keys) == 2
    assert len(set(keys)) == 2
    assert "corr-advisory" not in keys


def test_forseti_rule_cache_rejects_older_rule_revisions_and_timestamps() -> None:
    store = InMemoryStateStore()
    forseti = Forseti(state_store=store)

    async def _drive() -> None:
        await forseti.on_typed_message(
            "object.rule",
            {
                "producer_principal": "Mimir",
                "correlation_id": "corr-rule-new",
                "idempotency_key": "rule-new-key",
                "rule_id": "rule.scale",
                "action_type": "ops.scale-out",
                "state": "active",
                "revision": 3,
                "updated_at": "2026-10-01T00:10:00+00:00",
                "source_digest": "sha256:" + "3" * 64,
            },
        )
        await forseti.on_typed_message(
            "object.rule",
            {
                "producer_principal": "Mimir",
                "correlation_id": "corr-rule-old",
                "idempotency_key": "rule-old-key",
                "rule_id": "rule.scale",
                "action_type": "ops.scale-out",
                "state": "retired",
                "revision": 2,
                "updated_at": "2026-10-01T00:05:00+00:00",
                "source_digest": "sha256:" + "2" * 64,
            },
        )

    asyncio.run(_drive())

    assert forseti._rule_state.get("ops.scale-out")["state"] == "active"  # noqa: SLF001
    assert forseti.behavior_snapshot()["rule_state:active"] == 1
    assert forseti.behavior_snapshot()["rule_state:stale"] == 1


def test_forseti_validation_and_rule_ordering_helpers_cover_safety_edges() -> None:
    for kwargs in (
        {"rule_staleness_window": timedelta(0)},
        {"anomaly_action_sources": {"": object()}},
        {"anomaly_action_sources": {"x" * 129: object()}},
    ):
        try:
            Forseti(**kwargs)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:  # pragma: no cover - assertion helper
            raise AssertionError(f"Forseti accepted invalid constructor args: {kwargs}")

    try:
        Forseti(test_context_clock=lambda: datetime(2026, 10, 1))
    except ValueError:
        pass
    else:  # pragma: no cover - assertion helper
        raise AssertionError("Forseti accepted a naive clock")

    assert _rule_revision(True) is None
    assert _rule_revision(-1) is None
    assert _rule_revision("7") == 7
    assert _rule_revision("not-a-revision") is None
    assert _rule_updated_at("") is None
    assert _rule_updated_at("2026-10-01T00:00:00") is None
    assert _rule_updated_at("not-a-time") is None
    newer = _rule_updated_at("2026-10-01T00:10:00+00:00")
    older = _rule_updated_at("2026-10-01T00:05:00+00:00")
    assert newer is not None and older is not None
    assert _rule_state_is_newer(
        {"revision": "1"}, incoming_revision=2, incoming_updated_at=None, incoming_source_digest=""
    )
    assert not _rule_state_is_newer(
        {"revision": "2"}, incoming_revision=2, incoming_updated_at=None, incoming_source_digest=""
    )
    assert _rule_state_is_newer(
        {"updated_at": older.isoformat()},
        incoming_revision=None,
        incoming_updated_at=newer,
        incoming_source_digest="",
    )
    assert not _rule_state_is_newer(
        {"updated_at": newer.isoformat()},
        incoming_revision=None,
        incoming_updated_at=older,
        incoming_source_digest="",
    )
    assert _rule_state_is_newer(
        {"source_digest": "sha256:old"},
        incoming_revision=None,
        incoming_updated_at=None,
        incoming_source_digest="sha256:new",
    )
    assert not _rule_state_is_newer(
        {"source_digest": "sha256:same"},
        incoming_revision=None,
        incoming_updated_at=None,
        incoming_source_digest="sha256:same",
    )


def test_runtime_odin_down_terminal_hil_is_non_action_and_audited() -> None:
    provider = LocalEventBus()
    runtime = PantheonRuntime.build(
        provider=provider,
        raw_event_topic="fdai.events.r10-j2",
        disabled_agents=frozenset({"Odin"}),
    )
    thor = runtime.agents["Thor"]
    saga = runtime.agents["Saga"]
    assert isinstance(thor, Thor)
    assert isinstance(saga, Saga)

    async def _drive() -> None:
        await runtime.bridge.publish("Njord", "object.cost-anomaly", _cost_payload("corr-runtime"))
        await runtime.bridge.publish(
            "Freyr", "object.capacity-forecast", _capacity_payload("corr-runtime")
        )
        await _run_runtime_until(
            runtime,
            lambda: thor.behavior_snapshot().get("non_action_verdict_ignored") == 1,
        )

    asyncio.run(_drive())

    verdict = _provider_payloads(provider, "object.verdict")[-1]
    assert verdict["reason"] == "arbitration_owner_unavailable"
    assert verdict["risk_verdict"] == "hil"
    assert verdict["action_type"] == ""
    assert _provider_payloads(provider, "object.action-run") == []
    assert thor.behavior_snapshot()["non_action_verdict_ignored"] == 1
    replay = saga.replay_for_correlation("corr-runtime")
    assert replay
    assert replay[-1].topic == "object.verdict"
    assert verdict["arbitration"]["arbitration_request"]["resource_id"] == _RESOURCE
