"""Stale capacity and cost samples terminalize their durable duplicate fence."""

from __future__ import annotations

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.freyr import Freyr
from fdai.agents.njord import Njord
from fdai.shared.providers.cost_governance import CostAnalysisSample, CostAnomalyAdvisory
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_RELEASE = "sha256:" + "3" * 64


class _Advisory:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze_cost_sample(self, sample: CostAnalysisSample) -> CostAnomalyAdvisory | None:
        self.calls += 1
        return None

    def estimate_cost_effect(self, action_type: str) -> None:
        del action_type


async def test_freyr_stale_sample_is_terminal_and_replay_is_a_duplicate() -> None:
    store = InMemoryStateStore()
    freyr = Freyr(state_store=store)
    freyr.bind_bus(InMemoryBus(registry=load_pantheon()))
    await freyr.ingest_utilization(
        resource_id="vm-1",
        utilization=0.4,
        observed_at="2028-01-02T00:10:00+00:00",
        sample_key="sample-fresh",
    )

    for _ in range(2):
        await freyr.ingest_utilization(
            resource_id="vm-1",
            utilization=0.9,
            observed_at="2028-01-02T00:05:00+00:00",
            sample_key="sample-stale",
        )

    behaviors = freyr.behavior_snapshot()
    assert behaviors["capacity_sample:stale"] == 1
    assert behaviors["capacity_sample:duplicate"] == 1
    rows = await store.read_states("pantheon/freyr/accepted-samples/", limit=100)
    stale_rows = [row for row in rows if row.get("sample_key") == "sample-stale"]
    assert [row["state"] for row in stale_rows] == ["completed"]


async def test_njord_stale_sample_is_terminal_and_replay_is_a_duplicate() -> None:
    store = InMemoryStateStore()
    advisory = _Advisory()
    njord = Njord(
        advisory_provider=advisory,
        package_enabled=True,
        state_store=store,
        bus=InMemoryBus(registry=load_pantheon()),
    )
    fresh = {
        "scope": "scope-a",
        "amount_usd": 120.0,
        "observed_at": "2028-01-02T00:10:00+00:00",
        "source_authority": "azure-consumption-usage-details",
        "ontology_release_digest": _RELEASE,
    }
    stale = {**fresh, "amount_usd": 99.0, "observed_at": "2028-01-02T00:05:00+00:00"}
    await njord.ingest_cost_sample(**fresh)

    for _ in range(2):
        await njord.ingest_cost_sample(**stale)

    behaviors = njord.behavior_snapshot()
    assert behaviors["cost_sample:stale"] == 1
    assert behaviors["cost_sample:duplicate"] == 1
    assert advisory.calls == 1
    rows = await store.read_states("pantheon/njord/accepted-samples/", limit=100)
    assert len(rows) == 2
    assert {row["state"] for row in rows} == {"completed"}
