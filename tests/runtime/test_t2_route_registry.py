from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from fdai.runtime.t2_route_registry import (
    T2RouteRegistry,
    bind_t2_route_selector,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _clock() -> datetime:
    return datetime(2026, 8, 13, tzinfo=UTC)


def _run(
    correlation_id: str,
    *,
    action_type: str = "ops.switch-t2-proposer-route",
    prior_route: str = "primary",
    target_route: str = "secondary",
) -> object:
    return SimpleNamespace(
        action_type=action_type,
        correlation_id=correlation_id,
        resource_id="control-plane:t2-proposer",
        params={
            "target_resource_ref": "control-plane:t2-proposer",
            "target_route_ref": target_route,
            "prior_route_ref": prior_route,
            "reason_code": "t2_proposer_candidates_exhausted",
        },
    )


async def test_defaults_to_primary_without_persisted_override() -> None:
    registry = T2RouteRegistry(store=InMemoryStateStore(), clock=_clock)

    assert await registry.preferred_route(("primary", "secondary")) == "primary"


async def test_thor_switch_is_durable_audited_and_idempotent() -> None:
    store = InMemoryStateStore()
    registry = T2RouteRegistry(store=store, clock=_clock)

    assert await registry.execute({"run": _run("corr-1")}) is True
    assert await registry.execute({"run": _run("corr-1")}) is True

    state = await store.read_state("t2-recovery:route:proposer")
    assert state == {
        "active_route": "secondary",
        "prior_route": "primary",
        "change_correlation_id": "corr-1",
        "changed_at": "2026-08-13T00:00:00+00:00",
        "revision": 1,
    }
    assert await registry.preferred_route(("primary", "secondary")) == "secondary"
    audit = tuple(store.audit_entries)
    assert len(audit) == 1
    assert audit[0]["entry"]["actor"] == "Thor"
    assert audit[0]["entry"]["action_kind"] == "t2.proposer.route.switched"
    assert await store.verify_chain() is True


async def test_vidar_restores_only_the_failed_change() -> None:
    store = InMemoryStateStore()
    registry = T2RouteRegistry(store=store, clock=_clock)
    await registry.execute({"run": _run("corr-1")})

    receipt = await registry.rollback(
        {
            "action_type": "ops.switch-t2-proposer-route",
            "correlation_id": "corr-1",
        }
    )

    assert receipt == "t2-route:corr-1:rollback:2"
    state = await store.read_state("t2-recovery:route:proposer")
    assert state is not None
    assert state["active_route"] == "primary"
    assert state["revision"] == 2
    assert tuple(store.audit_entries)[-1]["entry"]["actor"] == "Vidar"


async def test_stale_rollback_cannot_revert_a_newer_route_change() -> None:
    store = InMemoryStateStore()
    registry = T2RouteRegistry(store=store, clock=_clock)
    await registry.execute({"run": _run("corr-1")})
    await registry.execute({"run": _run("corr-2", prior_route="secondary", target_route="primary")})

    receipt = await registry.rollback(
        {
            "action_type": "ops.switch-t2-proposer-route",
            "correlation_id": "corr-1",
        }
    )

    assert receipt == "t2-route:corr-1:rollback-superseded"
    state = await store.read_state("t2-recovery:route:proposer")
    assert state is not None
    assert state["active_route"] == "primary"
    assert state["change_correlation_id"] == "corr-2"
    assert tuple(store.audit_entries)[-1]["entry"]["action_kind"] == (
        "t2.proposer.route.rollback_superseded"
    )


async def test_unrelated_or_malformed_actions_fail_closed() -> None:
    registry = T2RouteRegistry(store=InMemoryStateStore(), clock=_clock)

    assert (
        await registry.execute({"run": _run("corr-1", action_type="ops.restart-service")}) is False
    )
    assert await registry.execute({"run": object()}) is False
    assert (
        await registry.rollback({"action_type": "ops.restart-service", "correlation_id": "corr-1"})
        is None
    )


async def test_stale_prior_route_is_rejected_without_mutation() -> None:
    store = InMemoryStateStore()
    registry = T2RouteRegistry(store=store, clock=_clock)
    await registry.execute({"run": _run("corr-1")})

    stale = _run("corr-2")
    assert await registry.execute({"run": stale}) is False

    state = await store.read_state("t2-recovery:route:proposer")
    assert state is not None
    assert state["active_route"] == "secondary"
    assert state["change_correlation_id"] == "corr-1"
    assert len(tuple(store.audit_entries)) == 1


class _Bindable:
    def __init__(self) -> None:
        self.registry: T2RouteRegistry | None = None

    def bind_route_selector(self, registry: T2RouteRegistry) -> None:
        self.registry = registry


def test_bind_helper_and_configuration_validation() -> None:
    registry = T2RouteRegistry(store=InMemoryStateStore(), clock=_clock)
    proposer = _Bindable()

    assert bind_t2_route_selector(proposer=proposer, registry=registry) is True
    assert proposer.registry is registry
    assert bind_t2_route_selector(proposer=object(), registry=registry) is False
    with pytest.raises(ValueError, match="at least two unique"):
        T2RouteRegistry(store=InMemoryStateStore(), routes=("primary",))
    with pytest.raises(ValueError, match="default"):
        T2RouteRegistry(
            store=InMemoryStateStore(),
            routes=("primary", "secondary"),
            default_route="missing",
        )
