"""Assurance Twin bootstrap keeps the evidence source optional and roles fixed."""

from __future__ import annotations

import pytest
from fdai.delivery.assurance_twin_review_producer import AssuranceTwinReviewProducer
from fdai.delivery.assurance_twin_writers import RetainedTwinEvidence
from fdai.runtime.bootstrap_core_model import (
    assurance_twin_inventory_dsn,
    build_assurance_twin_runtime_binding,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_ROSTER = ("Heimdall", "Forseti", "Saga")


class _UnavailableSource:
    async def read_posture(self, scope: str, revision: str) -> RetainedTwinEvidence | None:
        return None

    async def read_review(self, review_key: str, revision: str) -> RetainedTwinEvidence | None:
        return None


class _PostureEvaluator:
    async def evaluate_assurance_twin_posture(self, **_kwargs: object) -> object:
        raise AssertionError("bootstrap must not evaluate posture")

    async def run_assurance_twin_if_current(self, **_kwargs: object) -> bool:
        raise AssertionError("bootstrap must not publish posture")


@pytest.mark.parametrize(
    ("store", "roster"),
    [
        (None, _ROSTER),
        (InMemoryStateStore(), None),
        (InMemoryStateStore(), ("Heimdall", "Forseti")),
        (InMemoryStateStore(), ("Heimdall", "Saga")),
        (InMemoryStateStore(), ("Forseti", "Saga")),
    ],
)
def test_missing_store_or_accountable_agent_binds_no_twin_tasks(
    store: InMemoryStateStore | None,
    roster: tuple[str, ...] | None,
) -> None:
    publishers, writers = build_assurance_twin_runtime_binding(
        state_store=store,
        agents=roster,
        event_bus=InMemoryEventBus(),
        retained_source=_UnavailableSource(),
    )

    assert publishers == ()
    assert writers == ()


def test_state_store_source_is_bound_by_default_for_writers() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()

    publishers, writers = build_assurance_twin_runtime_binding(
        state_store=store,
        agents=_ROSTER,
        event_bus=bus,
        retained_source=None,
    )
    assert tuple(publisher.owner for publisher in publishers) == (
        "EvidenceSource",
        "Heimdall",
        "Forseti",
    )
    assert tuple(writer.owner for writer in writers) == ("Heimdall", "Forseti")

    source = _UnavailableSource()
    bound_publishers, bound_writers = build_assurance_twin_runtime_binding(
        state_store=store,
        agents=_ROSTER,
        event_bus=bus,
        retained_source=source,
    )
    assert tuple(publisher.owner for publisher in bound_publishers) == ("Heimdall", "Forseti")
    assert tuple(writer.owner for writer in bound_writers) == ("Heimdall", "Forseti")
    assert bound_publishers[0]._ledger is bound_publishers[1]._ledger
    assert all(writer._recorder._ledger is bound_publishers[0]._ledger for writer in bound_writers)
    assert all(publisher._bus is bus for publisher in bound_publishers)


def test_complete_posture_producer_binds_only_with_production_inputs() -> None:
    evaluator = _PostureEvaluator()
    publishers, writers = build_assurance_twin_runtime_binding(
        state_store=InMemoryStateStore(),
        agents=_ROSTER,
        event_bus=InMemoryEventBus(),
        retained_source=None,
        posture_evaluator=evaluator,  # type: ignore[arg-type]
        inventory_dsn="postgresql://example.invalid/fdai",
        posture_scope="subscription:scope-a",
        required_inventory_scopes=("scope-a",),
    )

    assert tuple(publisher.owner for publisher in publishers) == (
        "Heimdall",
        "Forseti",
        "EvidenceSource",
        "Heimdall",
        "Forseti",
    )
    assert tuple(writer.owner for writer in writers) == ("Heimdall", "Forseti")
    posture_producer, review_producer = publishers[0], publishers[1]
    assert isinstance(review_producer, AssuranceTwinReviewProducer)
    assert review_producer._inventory is posture_producer._inventory
    assert len(review_producer._effects) == 0
    heimdall, forseti = writers
    assert heimdall._generation_fence is evaluator
    assert heimdall._inventory_fence is posture_producer
    assert forseti._generation_fence is evaluator
    assert forseti._inventory_fence is review_producer


def test_injected_source_binds_no_review_producer_or_review_fence() -> None:
    publishers, writers = build_assurance_twin_runtime_binding(
        state_store=InMemoryStateStore(),
        agents=_ROSTER,
        event_bus=InMemoryEventBus(),
        retained_source=_UnavailableSource(),
        posture_evaluator=_PostureEvaluator(),  # type: ignore[arg-type]
        inventory_dsn="postgresql://example.invalid/fdai",
        posture_scope="subscription:scope-a",
        required_inventory_scopes=("scope-a",),
    )

    assert not any(isinstance(item, AssuranceTwinReviewProducer) for item in publishers)
    forseti = writers[1]
    assert forseti._generation_fence is None and forseti._inventory_fence is None


def test_inventory_dsn_precedes_shared_state_dsn() -> None:
    assert (
        assurance_twin_inventory_dsn(
            {
                "FDAI_INVENTORY_DSN": "postgresql://inventory.example/fdai",
                "FDAI_STATE_STORE_DSN": "postgresql://state.example/fdai",
            }
        )
        == "postgresql://inventory.example/fdai"
    )
    assert (
        assurance_twin_inventory_dsn({"FDAI_STATE_STORE_DSN": "postgresql://state.example/fdai"})
        == "postgresql://state.example/fdai"
    )
