"""Assurance Twin bootstrap keeps the evidence source optional and roles fixed."""

from __future__ import annotations

import pytest
from fdai.delivery.assurance_twin_writers import RetainedTwinEvidence
from fdai.runtime.bootstrap_assurance_twin import build_assurance_twin_runtime_binding
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_ROSTER = ("Heimdall", "Forseti", "Saga")


class _UnavailableSource:
    async def read_posture(self, scope: str, revision: str) -> RetainedTwinEvidence | None:
        return None

    async def read_review(self, review_key: str, revision: str) -> RetainedTwinEvidence | None:
        return None


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


def test_retained_source_is_required_only_for_writers() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()

    publishers, writers = build_assurance_twin_runtime_binding(
        state_store=store,
        agents=_ROSTER,
        event_bus=bus,
        retained_source=None,
    )
    assert tuple(publisher.owner for publisher in publishers) == ("Heimdall", "Forseti")
    assert writers == ()

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
