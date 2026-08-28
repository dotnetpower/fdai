from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.factory import CostRuntimeBindings
from fdai.agents._framework.pantheon import PANTHEON_NAMES
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.njord import Njord
from fdai.shared.providers.cost_governance import (
    CostAnalysisSample,
    CostAnomalyAdvisory,
    CostPackageActivation,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

_NOW = datetime(2028, 1, 2, tzinfo=UTC)
_RELEASE = "sha256:" + "3" * 64


class Advisory:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze_cost_sample(
        self,
        sample: CostAnalysisSample,
    ) -> CostAnomalyAdvisory | None:
        self.calls += 1
        return CostAnomalyAdvisory(
            scope_id=sample.scope_id,
            resource_id=sample.resource_id,
            amount_usd=sample.amount_usd,
            baseline_usd=Decimal("100"),
            ratio=sample.amount_usd / Decimal("100"),
            impact=Decimal("1"),
            recommendation="scale_down",
            correlation_id=sample.correlation_id,
            observed_at=sample.observed_at,
        )

    def estimate_cost_effect(self, action_type: str):
        return None


class Activation:
    def __init__(self, snapshot: CostPackageActivation | None) -> None:
        self.snapshot = snapshot
        self.calls = 0

    async def read_cost_activation(self, package_id: str):
        self.calls += 1
        return self.snapshot


def _snapshot(
    *,
    enabled: bool,
    previously_enabled: bool = False,
) -> CostPackageActivation:
    return CostPackageActivation(
        vertical_id="cost-governance",
        package_id="cost-governance",
        available=True,
        enabled=enabled,
        availability_reasons=(),
        package_version="0.1.0",
        image_digest=f"sha256:{'b' * 64}",
        asset_manifest_digest=f"sha256:{'c' * 64}",
        semantic_profile_digest=f"sha256:{'d' * 64}",
        previously_enabled=previously_enabled,
        revision=2,
        effective_at=_NOW,
        ontology_release_id="ontology-release:2028-01",
        ontology_release_digest=_RELEASE,
        source_authority="vertical-package-activation-store",
    )


def _event(observed_at: datetime, *, activation_revision: int = 2) -> dict[str, object]:
    return {
        "producer_principal": "Huginn",
        "correlation_id": f"cost:{observed_at.isoformat()}",
        "idempotency_key": f"cost:{observed_at.isoformat()}",
        "event_id": f"event:{observed_at.isoformat()}",
        "event_type": "specialist.cost_sample",
        "detected_at": observed_at.isoformat(),
        "attributes": {
            "scope": "scope-a",
            "resource_id": "resource-a",
            "amount_usd": 200.0,
            "activation_revision": activation_revision,
            "source_authority": "azure-cost-management-focus",
            "completeness": 1.0,
            "ontology_release_digest": _RELEASE,
        },
    }


def test_disabled_or_absent_provider_produces_zero_analysis_and_publications() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    advisory = Advisory()
    disabled = Njord(
        bus=bus,
        advisory_provider=advisory,
        activation_reader=Activation(_snapshot(enabled=False)),
        package_enabled=True,
    )
    absent = Njord(bus=bus, package_enabled=True)

    asyncio.run(disabled.on_typed_message("object.event", _event(_NOW + timedelta(seconds=1))))
    asyncio.run(absent.on_typed_message("object.event", _event(_NOW + timedelta(seconds=2))))

    assert advisory.calls == 0
    assert bus.messages_on("object.cost-anomaly") == []
    assert disabled.behavior_snapshot()["cost_sample:disabled"] == 1
    assert absent.behavior_snapshot()["cost_sample:disabled"] == 1


def test_enabled_sample_is_analyzed_and_only_njord_publishes_finding() -> None:
    registry = load_pantheon()
    bus = InMemoryBus(registry=registry)
    advisory = Advisory()
    njord = Njord(
        bus=bus,
        advisory_provider=advisory,
        activation_reader=Activation(_snapshot(enabled=True)),
        package_enabled=True,
    )

    asyncio.run(njord.on_typed_message("object.event", _event(_NOW)))

    assert advisory.calls == 1
    messages = bus.messages_on("object.cost-anomaly")
    assert len(messages) == 1 and messages[0].principal == "Njord"
    assert registry.get("Njord").owns == ("CostAnomaly", "Budget")


def test_broker_accepted_sample_drains_after_disable_but_new_sample_is_ignored() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    advisory = Advisory()
    njord = Njord(
        bus=bus,
        advisory_provider=advisory,
        activation_reader=Activation(
            _snapshot(enabled=False, previously_enabled=True),
        ),
        package_enabled=True,
    )

    asyncio.run(
        njord.on_typed_message(
            "object.event",
            _event(_NOW + timedelta(seconds=1), activation_revision=1),
        )
    )
    asyncio.run(
        njord.on_typed_message(
            "object.event",
            _event(_NOW - timedelta(seconds=1), activation_revision=2),
        )
    )

    assert advisory.calls == 1
    assert len(bus.messages_on("object.cost-anomaly")) == 1
    snapshot = njord.behavior_snapshot()
    assert snapshot["cost_sample:drained_after_disable"] == 1
    assert snapshot["cost_sample:disabled"] == 1


def test_runtime_injects_optional_provider_without_removing_any_agent() -> None:
    provider = InMemoryEventBus()
    advisory = Advisory()
    runtime = PantheonRuntime.build(
        provider=provider,
        raw_event_topic="fdai.events",
        cost_runtime=CostRuntimeBindings(
            advisory_provider=advisory,
            activation_reader=Activation(_snapshot(enabled=True)),
            package_enabled=True,
        ),
    )

    assert set(runtime.agents) == PANTHEON_NAMES
    assert isinstance(runtime.agents["Njord"], Njord)
    assert runtime.agents["Freyr"].spec.name == "Freyr"


def test_accepted_sample_changes_conversation_evidence_identity() -> None:
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        cost_runtime=CostRuntimeBindings(
            advisory_provider=Advisory(),
            activation_reader=Activation(_snapshot(enabled=True)),
            package_enabled=True,
        ),
    )
    njord = runtime.agents["Njord"]
    assert isinstance(njord, Njord)
    before = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Njord",
            tool_id="read_cost_samples",
            question="cost samples",
        )
    )

    asyncio.run(njord.on_typed_message("object.event", _event(_NOW)))
    after = asyncio.run(
        runtime.invoke_conversation_tool(
            agent_name="Njord",
            tool_id="read_cost_samples",
            question="cost samples",
        )
    )

    assert before.evidence_refs != after.evidence_refs


def test_package_has_no_direct_agent_call_or_authority_field() -> None:
    root = Path(__file__).resolve().parents[4]
    package = root / "extensions/cost-governance/src/fdai_cost_governance"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in package.glob("*.py")
        if path.name != "__about__.py"
    )
    assert "fdai.agents" not in source
    assert ".on_typed_message(" not in source
    assert ".ingest_cost_sample(" not in source
    for forbidden in (
        "approval_authority",
        "execution_authority",
        "promotion_authority",
        "executor_principal",
    ):
        assert forbidden not in source


def test_replay_scenario_reaches_all_fixed_responsibilities_without_live_claim() -> None:
    root = Path(__file__).resolve().parents[4]
    scenario = json.loads(
        (
            root / "services/core-control-plane/tests/scenarios/cost-governance-w3a-replay.json"
        ).read_text(encoding="utf-8")
    )
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        cost_runtime=CostRuntimeBindings(
            advisory_provider=Advisory(),
            activation_reader=Activation(_snapshot(enabled=True)),
            package_enabled=True,
        ),
    )
    subscribed_agents = {
        name for bindings in runtime.bridge._subs.values() for name, _handler in bindings
    }

    assert scenario["live_operation"] is False
    assert set(scenario["responsible_agents"]) == PANTHEON_NAMES
    assert set(runtime.agents) == PANTHEON_NAMES
    assert subscribed_agents - {"runtime-observer"} == PANTHEON_NAMES
    assert scenario["expected"]["mutation_principal"] == "Thor"
