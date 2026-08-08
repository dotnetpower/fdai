"""Durable route selection plus Thor/Vidar adapters for T2 proposer recovery."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Final

from fdai.shared.providers.state_store import StateStore

_ROUTE_STATE_KEY: Final = "t2-recovery:route:proposer"
_ROUTE_ACTION: Final = "ops.switch-t2-proposer-route"


class T2RouteRegistry:
    """Select, switch, and conditionally restore one bounded proposer route."""

    __slots__ = ("_clock", "_default_route", "_routes", "_store")

    def __init__(
        self,
        *,
        store: StateStore,
        routes: tuple[str, ...] = ("primary", "secondary"),
        default_route: str = "primary",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if len(routes) < 2 or len(routes) != len(set(routes)):
            raise ValueError("T2 route registry requires at least two unique routes")
        if default_route not in routes:
            raise ValueError("T2 route registry default MUST be an available route")
        self._store = store
        self._routes = routes
        self._default_route = default_route
        self._clock = clock

    async def preferred_route(self, available_routes: tuple[str, ...]) -> str:
        """Return the persisted route when it remains available to composition."""

        state = await self._store.read_state(_ROUTE_STATE_KEY)
        selected = str(state.get("active_route") or "") if state is not None else ""
        if selected in available_routes:
            return selected
        if self._default_route in available_routes:
            return self._default_route
        return available_routes[0]

    async def execute(self, context: dict[str, Any]) -> bool:
        """Thor adapter: switch to the alternate route with durable CAS and audit."""

        run = context.get("run")
        if getattr(run, "action_type", None) != _ROUTE_ACTION:
            return False
        correlation_id = str(getattr(run, "correlation_id", ""))
        resource_id = str(getattr(run, "resource_id", "") or "")
        if not correlation_id or resource_id != "control-plane:t2-proposer":
            return False
        params = getattr(run, "params", None)
        if not isinstance(params, Mapping):
            return False
        state = await self._store.read_state(_ROUTE_STATE_KEY)
        if state is not None and state.get("change_correlation_id") == correlation_id:
            return True
        active_route = self._active_route(state)
        prior_route = str(params.get("prior_route_ref") or "")
        target_route = str(params.get("target_route_ref") or "")
        if (
            str(params.get("target_resource_ref") or "") != resource_id
            or prior_route != active_route
            or target_route not in self._routes
            or target_route == active_route
            or not str(params.get("reason_code") or "")
        ):
            return False
        changed_at = self._timestamp()
        if state is None:
            changed = await self._store.write_state_with_audit_if_absent(
                _ROUTE_STATE_KEY,
                self._switched_state(
                    revision=1,
                    active_route=target_route,
                    prior_route=active_route,
                    correlation_id=correlation_id,
                    changed_at=changed_at,
                ),
                self._audit(
                    actor="Thor",
                    action_kind="t2.proposer.route.switched",
                    correlation_id=correlation_id,
                    prior_route=active_route,
                    active_route=target_route,
                    revision=1,
                    recorded_at=changed_at,
                ),
            )
        else:
            revision = _revision(state)
            changed = await self._store.compare_and_set_state_with_audit(
                _ROUTE_STATE_KEY,
                self._switched_state(
                    revision=revision + 1,
                    active_route=target_route,
                    prior_route=active_route,
                    correlation_id=correlation_id,
                    changed_at=changed_at,
                ),
                expected_revision=revision,
                audit_entry=self._audit(
                    actor="Thor",
                    action_kind="t2.proposer.route.switched",
                    correlation_id=correlation_id,
                    prior_route=active_route,
                    active_route=target_route,
                    revision=revision + 1,
                    recorded_at=changed_at,
                ),
            )
        if not changed:
            current = await self._store.read_state(_ROUTE_STATE_KEY)
            return bool(current and current.get("change_correlation_id") == correlation_id)
        current = await self._store.read_state(_ROUTE_STATE_KEY)
        return bool(
            current
            and current.get("active_route") == target_route
            and current.get("change_correlation_id") == correlation_id
        )

    async def rollback(self, action_run: dict[str, Any]) -> str | None:
        """Vidar adapter: restore only the route changed by this failed run."""

        if action_run.get("action_type") != _ROUTE_ACTION:
            return None
        correlation_id = str(action_run.get("correlation_id") or "")
        if not correlation_id:
            return None
        state = await self._store.read_state(_ROUTE_STATE_KEY)
        if state is None or state.get("change_correlation_id") != correlation_id:
            await self._store.append_audit_entry(
                {
                    "event_id": correlation_id,
                    "correlation_id": correlation_id,
                    "idempotency_key": f"{correlation_id}:route-rollback-superseded",
                    "actor": "Vidar",
                    "producer_principal": "Vidar",
                    "action_kind": "t2.proposer.route.rollback_superseded",
                    "mode": "enforce",
                    "recorded_at": self._timestamp(),
                }
            )
            return f"t2-route:{correlation_id}:rollback-superseded"
        revision = _revision(state)
        active_route = self._active_route(state)
        prior_route = str(state.get("prior_route") or "")
        if prior_route not in self._routes:
            return None
        recorded_at = self._timestamp()
        restored = await self._store.compare_and_set_state_with_audit(
            _ROUTE_STATE_KEY,
            {
                "active_route": prior_route,
                "prior_route": active_route,
                "change_correlation_id": f"{correlation_id}:rollback",
                "changed_at": recorded_at,
                "revision": revision + 1,
            },
            expected_revision=revision,
            audit_entry=self._audit(
                actor="Vidar",
                action_kind="t2.proposer.route.rolled_back",
                correlation_id=correlation_id,
                prior_route=active_route,
                active_route=prior_route,
                revision=revision + 1,
                recorded_at=recorded_at,
            ),
        )
        if not restored:
            return None
        return f"t2-route:{correlation_id}:rollback:{revision + 1}"

    def _active_route(self, state: Mapping[str, Any] | None) -> str:
        active = str(state.get("active_route") or "") if state is not None else ""
        return active if active in self._routes else self._default_route

    @staticmethod
    def _switched_state(
        *,
        revision: int,
        active_route: str,
        prior_route: str,
        correlation_id: str,
        changed_at: str,
    ) -> dict[str, object]:
        return {
            "active_route": active_route,
            "prior_route": prior_route,
            "change_correlation_id": correlation_id,
            "changed_at": changed_at,
            "revision": revision,
        }

    @staticmethod
    def _audit(
        *,
        actor: str,
        action_kind: str,
        correlation_id: str,
        prior_route: str,
        active_route: str,
        revision: int,
        recorded_at: str,
    ) -> dict[str, object]:
        return {
            "event_id": correlation_id,
            "correlation_id": correlation_id,
            "idempotency_key": f"{correlation_id}:{action_kind}:{revision}",
            "actor": actor,
            "producer_principal": actor,
            "action_kind": action_kind,
            "mode": "enforce",
            "resource_id": "control-plane:t2-proposer",
            "prior_route_ref": prior_route,
            "active_route_ref": active_route,
            "revision": revision,
            "recorded_at": recorded_at,
        }

    def _timestamp(self) -> str:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("T2 route registry clock MUST be timezone-aware")
        return value.isoformat()


def _revision(state: Mapping[str, Any]) -> int:
    revision = int(state.get("revision") or 0)
    if revision < 1:
        raise ValueError("T2 route registry revision MUST be positive")
    return revision


def bind_t2_route_selector(*, proposer: object, registry: T2RouteRegistry) -> bool:
    """Bind route selection only when the configured proposer supports it."""

    bind = getattr(proposer, "bind_route_selector", None)
    if not callable(bind):
        return False
    bind(registry)
    return True


__all__ = ["T2RouteRegistry", "bind_t2_route_selector"]
