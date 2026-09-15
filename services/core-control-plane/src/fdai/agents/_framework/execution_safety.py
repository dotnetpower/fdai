"""Composition helpers for Thor's pre-execution and HIL safety boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
from collections.abc import Awaitable, Callable, Coroutine, Mapping

from fdai.agents._framework.base import Agent
from fdai.agents._framework.pantheon import HARD_DEPENDENCY_AGENTS, PANTHEON_NAMES
from fdai.agents.saga import Saga
from fdai.agents.thor import ActionExecutor, ActionRun, ActionRunStore, Thor
from fdai.shared.providers.resource_lock import ResourceLock

_LOG = logging.getLogger(__name__)


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
    has_rollback: bool,
    has_vidar_state_store: bool,
    has_var_state_store: bool,
    has_approver_authorizer: bool,
    resource_lock: ResourceLock | None,
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
    if not has_rollback:
        missing.append("rollback_executors")
    if not has_vidar_state_store:
        missing.append("vidar_state_store")
    if not has_var_state_store:
        missing.append("var_state_store")
    if not has_approver_authorizer:
        missing.append("approver_authorizer")
    if resource_lock is None:
        missing.append("execution_resource_lock")
    elif not resource_lock.distributed:
        missing.append("distributed_execution_resource_lock")
    if missing:
        raise ValueError(
            "pantheon enforce mode requires explicit durable safety bindings: " + ", ".join(missing)
        )


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


async def maintain_agents(agents: Mapping[str, Agent], interval: float) -> None:
    """Expire bounded HIL waits while the Pantheon runtime is active."""

    while True:
        await asyncio.sleep(interval)
        thor = agents.get("Thor")
        if isinstance(thor, Thor):
            try:
                await thor.expire_pending_approvals()
            except Exception:  # noqa: BLE001 - one failed expiry must not stop later safety ticks
                _LOG.exception("pantheon_hil_expiry_failed")


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
