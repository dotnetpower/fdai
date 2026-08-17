"""Fail-closed scalar and graph simulation evidence for T1 fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.assurance_twin import DynamicRuntimeCoordinator, GraphDynamicRuntimeCoordinator
from fdai.core.tiers.t1_lightweight.tier import T1Decision
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.core.control_loop.fallback")


@dataclass(frozen=True, slots=True)
class DynamicGuardDecision:
    """Summarize whether configured dynamic simulations permit fallback reuse."""

    configured: bool
    passed: bool
    reasons: tuple[str, ...] = ()


class DynamicSimulationAuditMixin:
    """Record scalar and graph simulation evidence before T1 action reuse."""

    _audit_store: StateStore
    _dynamic_runtime_coordinator: DynamicRuntimeCoordinator | None
    _graph_dynamic_runtime_coordinator: GraphDynamicRuntimeCoordinator | None

    async def _simulate_and_audit_dynamic(
        self,
        *,
        event: Event,
        t1: T1Decision,
    ) -> DynamicGuardDecision:
        coordinator = self._dynamic_runtime_coordinator
        if t1.best_match is None:
            return DynamicGuardDecision(False, True)
        if coordinator is None:
            return await self._simulate_and_audit_graph_dynamic(event=event, t1=t1)
        reasons: list[str] = []
        try:
            result = await coordinator.simulate(event=event, action=t1.best_match.action)
        except Exception as exc:  # noqa: BLE001 - fail closed into Dynamic hold
            simulation = None
            reason = f"simulation_failed:{type(exc).__name__}"
            reasons.append(reason)
        else:
            simulation = result.simulation
            reason = result.reason
            if simulation is None:
                reasons.append(reason)
            elif simulation.requires_review:
                reasons.append("scalar_simulation_requires_review")
        entry = {
            "event_id": str(event.event_id),
            "correlation_id": event.correlation_id or str(event.event_id),
            "idempotency_key": f"{event.idempotency_key}:dynamic_simulation",
            "actor": "fdai.core.assurance_twin",
            "action_kind": "dynamic.simulation",
            "mode": Mode.SHADOW.value,
            "simulation_reason": reason,
            "simulation_id": simulation.simulation_id if simulation else None,
            "simulation_requires_review": simulation.requires_review if simulation else True,
            "ordered_branch_ids": list(simulation.ordered_branch_ids) if simulation else [],
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }
        try:
            await self._audit_store.append_audit_entry(entry)
        except Exception:  # noqa: BLE001 - missing decision evidence must hold
            reasons.append("scalar_simulation_audit_failed")
            _LOGGER.warning(
                "dynamic_simulation_audit_failed",
                extra={
                    "event_id": str(event.event_id),
                    "simulation_reason": reason,
                },
                exc_info=True,
            )
        graph = await self._simulate_and_audit_graph_dynamic(event=event, t1=t1)
        reasons.extend(graph.reasons)
        normalized = tuple(sorted(set(reasons)))
        return DynamicGuardDecision(True, not normalized, normalized)

    async def _simulate_and_audit_graph_dynamic(
        self,
        *,
        event: Event,
        t1: T1Decision,
    ) -> DynamicGuardDecision:
        coordinator = self._graph_dynamic_runtime_coordinator
        if coordinator is None or t1.best_match is None:
            return DynamicGuardDecision(False, True)
        reasons: list[str] = []
        try:
            result = await coordinator.simulate(event=event, action=t1.best_match.action)
        except Exception as exc:  # noqa: BLE001 - fail closed into Dynamic hold
            simulation = None
            reason = f"graph_simulation_failed:{type(exc).__name__}"
            reasons.append(reason)
        else:
            simulation = result.simulation
            reason = result.reason
            if simulation is None:
                reasons.append(reason)
            elif simulation.requires_review:
                reasons.extend(simulation.reason_codes or ("graph_simulation_requires_review",))
        entry = {
            "event_id": str(event.event_id),
            "correlation_id": event.correlation_id or str(event.event_id),
            "idempotency_key": f"{event.idempotency_key}:graph_dynamic_simulation",
            "actor": "fdai.core.assurance_twin",
            "action_kind": "dynamic.graph_simulation",
            "mode": Mode.SHADOW.value,
            "simulation_reason": reason,
            "trajectory_digest": (
                simulation.active_trajectory.digest if simulation is not None else None
            ),
            "simulation_requires_review": (
                simulation.requires_review if simulation is not None else True
            ),
            "reason_codes": list(simulation.reason_codes) if simulation is not None else [],
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }
        try:
            await self._audit_store.append_audit_entry(entry)
        except Exception:  # noqa: BLE001 - missing decision evidence must hold
            reasons.append("graph_simulation_audit_failed")
            _LOGGER.warning(
                "graph_dynamic_simulation_audit_failed",
                extra={"event_id": str(event.event_id), "simulation_reason": reason},
                exc_info=True,
            )
        normalized = tuple(sorted(set(reasons)))
        return DynamicGuardDecision(True, not normalized, normalized)


__all__ = ["DynamicGuardDecision", "DynamicSimulationAuditMixin"]
