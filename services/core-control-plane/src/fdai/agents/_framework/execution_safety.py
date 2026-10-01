"""Composition helpers for Thor's pre-execution and HIL safety boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from typing import Any

from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.base import Agent
from fdai.agents._framework.pantheon import HARD_DEPENDENCY_AGENTS, PANTHEON_NAMES
from fdai.agents._framework.thor_preflight import ThorPreflightSimulator
from fdai.agents.saga import Saga
from fdai.agents.thor import ActionExecutor, ActionRun, ActionRunStore, Thor
from fdai.shared.providers.resource_lock import ResourceLock

_LOG = logging.getLogger(__name__)
_ROLLBACK_CONTRACTS_WITHOUT_EXECUTOR = frozenset(
    {
        "irreversible",
        "not_applicable",
        "not-applicable",
        "not_required",
        "none",
    }
)


def validate_disabled_agents(disabled_agents: frozenset[str] | None) -> frozenset[str]:
    """Reject unknown or safety-critical disabled agents before runtime construction."""
    disabled = frozenset(disabled_agents or frozenset())
    unknown = disabled - PANTHEON_NAMES
    if unknown:
        raise ValueError(f"unknown agents in disabled set: {sorted(unknown)}")
    forbidden = disabled & HARD_DEPENDENCY_AGENTS
    if forbidden:
        raise ValueError(
            "hard-dependency agents cannot be disabled (audit / rollback "
            f"are mutation safety invariants): {sorted(forbidden)}"
        )
    return disabled


async def refuse_unbound_action(context: dict[str, object]) -> bool:
    """A path-specific binding never enables Thor's test-only default for unrelated actions."""
    del context
    raise RuntimeError(
        "general Thor execution is unbound; only the separately bound path is available"
    )


def validate_enforce_bindings(
    *,
    enforce: bool,
    has_executor: bool,
    has_state_store: bool,
    saga: Saga | None,
    rollback_executors: Mapping[str, object] | None,
    action_rollback_executors: Mapping[tuple[str, str], object] | None,
    action_semantics: ActionSemanticsCatalog | None,
    has_vidar_state_store: bool,
    has_var_state_store: bool,
    has_forseti_state_store: bool,
    has_approver_authorizer: bool,
    resource_lock: ResourceLock | None,
    has_action_semantics: bool,
    has_preflight_simulator: bool,
) -> None:
    """Reject enforce mode until every durable safety binding is present."""

    if not enforce:
        return
    missing: list[str] = []
    if not has_executor:
        missing.append("thor_executor")
    if not has_state_store:
        missing.append("thor_state_store")
    if saga is None or not saga.durable_audit:
        missing.append("durable_saga")
    missing.extend(
        _missing_rollback_executor_bindings(
            action_semantics=action_semantics,
            rollback_executors=rollback_executors,
            action_rollback_executors=action_rollback_executors,
        )
    )
    if not has_vidar_state_store:
        missing.append("vidar_state_store")
    if not has_var_state_store:
        missing.append("var_state_store")
    if not has_forseti_state_store:
        missing.append("forseti_state_store")
    if not has_approver_authorizer:
        missing.append("approver_authorizer")
    if resource_lock is None:
        missing.append("execution_resource_lock")
    elif not resource_lock.distributed:
        missing.append("distributed_execution_resource_lock")
    if not has_action_semantics:
        missing.append("action_type_catalog")
    if not has_preflight_simulator:
        missing.append("thor_preflight_simulator")
    if missing:
        raise ValueError(
            "pantheon enforce mode requires explicit durable safety bindings: " + ", ".join(missing)
        )


def _missing_rollback_executor_bindings(
    *,
    action_semantics: ActionSemanticsCatalog | None,
    rollback_executors: Mapping[str, object] | None,
    action_rollback_executors: Mapping[tuple[str, str], object] | None,
) -> list[str]:
    if action_semantics is None:
        return ["rollback_executors"]
    generic_contracts = frozenset(str(contract) for contract in (rollback_executors or {}))
    action_pairs = frozenset(
        (str(action_type), str(contract))
        for action_type, contract in (action_rollback_executors or {})
    )
    missing = [
        f"rollback_executors[{action_type}:{contract}]"
        for action_type, contract in _rollback_executor_requirements(action_semantics)
        if contract not in generic_contracts and (action_type, contract) not in action_pairs
    ]
    if not missing and not generic_contracts and not action_pairs:
        return ["rollback_executors"]
    return missing


def _rollback_executor_requirements(
    action_semantics: ActionSemanticsCatalog,
) -> tuple[tuple[str, str], ...]:
    requirements: list[tuple[str, str]] = []
    for action_type, contract in action_semantics.rollback_by_id.items():
        normalized_contract = str(contract).strip()
        if not normalized_contract:
            continue
        if normalized_contract in _ROLLBACK_CONTRACTS_WITHOUT_EXECUTOR:
            continue
        if action_semantics.irreversible(action_type):
            continue
        requirements.append((action_type, normalized_contract))
    return tuple(sorted(requirements))


def bind_execution_audit(*, thor: Thor, saga: Saga | None, enforce: bool) -> None:
    """Require one durable Saga-owned intent receipt before enforce-mode I/O."""

    if saga is None or not saga.durable_audit:
        thor.set_execution_audit_recorder(None, required=enforce)
        return

    async def _record(run: ActionRun) -> str:
        intent = {
            "action_type": run.action_type,
            "resource_id": run.resource_id,
            "action_idempotency_key": run.idempotency_key,
            "resolved_autonomy_ceiling": run.resolved_autonomy_ceiling.value,
            "original_quorum_required": run.original_quorum_required,
            "effective_quorum_required": run.effective_quorum_required,
            "development_authority": run.development_authority,
            "params": run.params,
            "decision_case": run.decision_case,
            "operational_context": run.operational_context,
            "workflow_action": run.workflow_action,
            "kinetic_proposal": run.kinetic_proposal,
        }
        intent_digest = hashlib.sha256(
            json.dumps(
                intent,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        result = saga.audit_chain.append(
            principal="Saga",
            topic="object.execution-intent",
            correlation_id=run.correlation_id,
            payload={**intent, "intent_digest": f"sha256:{intent_digest}"},
        )
        entry = await result if inspect.isawaitable(result) else result
        return entry.entry_hash

    thor.set_execution_audit_recorder(_record, required=enforce)


def configure_thor_execution(
    *,
    thor: Thor,
    executor: ActionExecutor | None,
    state_store: ActionRunStore | None,
    resource_lock: ResourceLock | None,
    saga: Saga | None,
    enforce: bool,
    human_access_bound: bool,
    preflight_simulator: ThorPreflightSimulator | None = None,
) -> None:
    """Bind explicit execution/audit/lock seams while keeping unrelated unbound actions denied."""
    if executor is not None:
        thor.set_executor(executor)
    elif enforce and human_access_bound:
        thor.set_executor(refuse_unbound_action)
    thor.set_shadow(not enforce)
    if state_store is not None:
        thor.set_state_store(state_store)
    bind_execution_audit(thor=thor, saga=saga, enforce=enforce)
    thor.set_execution_resource_lock(resource_lock, required=enforce)
    thor.set_preflight_simulator(preflight_simulator)


async def maintain_agents(
    agents: Mapping[str, Agent],
    interval: float,
    *,
    tick_timeout: float = 5.0,
    max_in_flight: int | None = None,
) -> None:
    """Run isolated per-agent maintenance while consumers stay active.

    A maintenance tick is cheap, bounded, and side-effect constrained to each
    agent's own framework state: Thor expires HIL waits, the base agent drains
    its proposal queue, Saga verifies its local chain, and Norns flushes inert
    candidates. Ticks run concurrently and never block the event-bus consumers.
    One timeout or exception increments that agent's behavior counter and does
    not cancel sibling ticks.
    """

    in_flight: dict[tuple[str, str], asyncio.Task[Any]] = {}
    in_flight_limit = max_in_flight if max_in_flight is not None else max(1, len(agents) * 2)
    if in_flight_limit < 1:
        raise ValueError("max_in_flight MUST be >= 1")
    while True:
        await asyncio.sleep(interval)
        tasks = [
            asyncio.create_task(
                _run_agent_maintenance(agent, tick_timeout, in_flight, in_flight_limit),
                name=f"pantheon-maintenance.{name}",
            )
            for name, agent in agents.items()
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def _run_agent_maintenance(
    agent: Agent,
    tick_timeout: float,
    in_flight: dict[tuple[str, str], asyncio.Task[Any]] | None = None,
    in_flight_limit: int = 1,
) -> None:
    in_flight = in_flight if in_flight is not None else {}
    try:
        if isinstance(agent, Thor):
            if not await _run_maintenance_step(
                agent,
                agent.expire_pending_approvals(),
                tick_timeout,
                in_flight,
                in_flight_limit,
                step="expire_pending_approvals",
            ):
                return
        if not await _run_maintenance_step(
            agent,
            agent.maintenance_tick(),
            tick_timeout,
            in_flight,
            in_flight_limit,
            step="maintenance_tick",
        ):
            return
        agent.record_behavior("maintenance_tick:completed")
    except Exception:  # noqa: BLE001 - one failed tick must not stop later safety ticks
        agent.record_behavior("maintenance_tick:failed")
        _LOG.exception("pantheon_agent_maintenance_failed", extra={"agent": agent.spec.name})


async def _run_maintenance_step(
    agent: Agent,
    operation: Awaitable[Any],
    tick_timeout: float,
    in_flight: dict[tuple[str, str], asyncio.Task[Any]],
    in_flight_limit: int,
    *,
    step: str,
) -> bool:
    """Run one maintenance step with a deadline that does not cancel commits."""

    key = (agent.spec.name, step)
    existing = in_flight.get(key)
    if existing is not None and not existing.done():
        agent.record_behavior("maintenance_tick:skipped_in_flight")
        _close_unscheduled(operation)
        return False
    if len([task for task in in_flight.values() if not task.done()]) >= in_flight_limit:
        agent.record_behavior("maintenance_tick:skipped_capacity")
        _close_unscheduled(operation)
        return False
    task: asyncio.Future[Any] = asyncio.ensure_future(operation)
    if isinstance(task, asyncio.Task):
        task.set_name(f"pantheon-maintenance.{agent.spec.name}.{step}")
        in_flight[key] = task
    try:
        await asyncio.wait_for(asyncio.shield(task), tick_timeout)
        in_flight.pop(key, None)
        return True
    except TimeoutError:
        agent.record_behavior("maintenance_tick:timeout")
        _LOG.warning(
            "pantheon_agent_maintenance_timeout",
            extra={"agent": agent.spec.name, "step": step},
        )
        task.add_done_callback(
            lambda done: _observe_timed_out_maintenance(agent, step, done, in_flight)
        )
        return False
    except Exception:
        in_flight.pop(key, None)
        raise


def _observe_timed_out_maintenance(
    agent: Agent,
    step: str,
    task: asyncio.Future[Any],
    in_flight: dict[tuple[str, str], asyncio.Task[Any]],
) -> None:
    in_flight.pop((agent.spec.name, step), None)
    try:
        task.result()
    except Exception:  # noqa: BLE001 - late failure is observability only
        agent.record_behavior("maintenance_tick:late_failed")
        _LOG.exception(
            "pantheon_agent_maintenance_late_failed",
            extra={"agent": agent.spec.name, "step": step},
        )


def _close_unscheduled(operation: Awaitable[Any]) -> None:
    close = getattr(operation, "close", None)
    if callable(close):
        close()


async def run_with_maintenance(
    *,
    run_consumers: Callable[[], Awaitable[None]],
    agents: Mapping[str, Agent],
    heartbeat: Callable[[float], Coroutine[object, object, None]],
    heartbeat_interval: float | None,
) -> None:
    """Run consumers with bounded HIL maintenance and optional health logging."""

    maintenance = asyncio.create_task(maintain_agents(agents, 30.0), name="pantheon-maintenance")
    heartbeat_task: asyncio.Task[None] | None = (
        asyncio.create_task(
            heartbeat(heartbeat_interval),
            name="pantheon-heartbeat",
        )
        if heartbeat_interval is not None and heartbeat_interval > 0
        else None
    )
    try:
        await run_consumers()
    finally:
        for task in (heartbeat_task, maintenance):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110 - cleanup
                pass


__all__ = [
    "bind_execution_audit",
    "configure_thor_execution",
    "maintain_agents",
    "refuse_unbound_action",
    "run_with_maintenance",
    "validate_enforce_bindings",
]
