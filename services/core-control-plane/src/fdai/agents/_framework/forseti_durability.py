"""Durable restart projections for Forseti-owned judgment state."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, cast

from fdai.agents._framework.cross_vertical_candidates import CandidateClosure
from fdai.agents._framework.forseti_arbitration_contract import (
    arbitration_owner as _arbitration_owner,
)
from fdai.agents._framework.runtime_health import AGENT_DEGRADATION_POLICIES, evaluate_degradation

_MAX_RESOURCES = 10_000


async def durable_cross_vertical_completed(host: Any, correlation_id: str) -> bool:
    store = host._forseti_state_store
    if store is None:
        return False
    return (
        await store.read_state(f"pantheon/forseti/cross-vertical-completed|{correlation_id}")
    ) is not None


async def mark_cross_vertical_completed(host: Any, correlation_id: str, reason: str) -> None:
    host._cross_vertical_candidates.mark_completed(correlation_id)
    store = host._forseti_state_store
    if store is None or not correlation_id:
        return
    await store.write_state_if_absent(
        f"pantheon/forseti/cross-vertical-completed|{correlation_id}",
        {
            "kind": "cross_vertical_completed",
            "correlation_id": correlation_id,
            "reason": reason,
            "recorded_at": host._test_context_clock().isoformat(),
        },
    )


async def persist_cross_vertical_pending(host: Any, correlation_id: str) -> None:
    store = host._forseti_state_store
    if store is None or not correlation_id:
        return
    key = f"pantheon/forseti/cross-vertical-pending|{correlation_id}"
    if await store.read_state(key) is not None:
        return
    payloads = host._cross_vertical_candidates.pending_payloads(correlation_id)
    if not payloads:
        return
    await store.write_state_if_absent(
        key,
        {
            "kind": "cross_vertical_pending",
            "status": "pending",
            "correlation_id": correlation_id,
            "resource_id": str(payloads[0].get("resource_id") or ""),
            "observed_at": str(payloads[0].get("observed_at") or ""),
            "deadline_at": (
                host._test_context_clock() + timedelta(seconds=host._cross_vertical_timeout_seconds)
            ).isoformat(),
            "candidates": list(payloads),
        },
    )


async def persist_arbitration_resource(host: Any, correlation_id: str, resource_id: str) -> None:
    store = host._forseti_state_store
    if store is None or not correlation_id or not resource_id:
        return
    await store.write_state_if_absent(
        f"pantheon/forseti/arbitration-resource|{correlation_id}",
        {
            "kind": "arbitration_resource",
            "correlation_id": correlation_id,
            "resource_id": resource_id,
            "recorded_at": host._test_context_clock().isoformat(),
        },
    )


async def durable_arbitration_resource(host: Any, correlation_id: str) -> str | None:
    store = host._forseti_state_store
    if store is None or not correlation_id:
        return None
    row = await store.read_state(f"pantheon/forseti/arbitration-resource|{correlation_id}")
    if row is None:
        return None
    resource_id = str(row.get("resource_id") or "")
    return resource_id or None


async def mark_arbitration_completed(host: Any, correlation_id: str, outcome: str) -> None:
    store = host._forseti_state_store
    if store is None or not correlation_id:
        return
    await store.write_state_if_absent(
        f"pantheon/forseti/arbitration-completed|{correlation_id}",
        {
            "kind": "arbitration_completed",
            "correlation_id": correlation_id,
            "outcome": outcome,
            "recorded_at": host._test_context_clock().isoformat(),
        },
    )


async def durable_arbitration_completed(host: Any, correlation_id: str) -> bool:
    store = host._forseti_state_store
    if store is None or not correlation_id:
        return False
    return (
        await store.read_state(f"pantheon/forseti/arbitration-completed|{correlation_id}")
    ) is not None


async def persist_domain_advice(host: Any, resource_id: str, *, status: str = "pending") -> None:
    store = host._forseti_state_store
    if store is None or not resource_id:
        return
    await store.write_state(
        f"pantheon/forseti/domain-advice|{resource_id}",
        {
            "kind": "domain_advice",
            "status": status,
            "resource_id": resource_id,
            "advice": dict(host._domain_advice.get(resource_id) or {}),
            "impacts": dict(host._domain_impact.get(resource_id) or {}),
            "observed_at": host._domain_observed_at.get(resource_id) or "",
            "arguments": dict(host._domain_arguments.get(resource_id) or {}),
            "recorded_at": host._test_context_clock().isoformat(),
        },
    )


async def rehydrate_arbitration_state(host: Any) -> int:
    store = host._forseti_state_store
    if store is None:
        return 0
    restored = await _rehydrate_arbitration_resources(host, store)
    restored += await _rehydrate_arbitration_completions(host, store)
    restored += await _rehydrate_domain_advice(host, store)
    restored += await _rehydrate_cross_vertical_completions(host, store)
    restored += await _rehydrate_cross_vertical_pending(host, store)
    return restored


async def close_unowned_arbitration(
    host: Any,
    correlation_id: str,
    *,
    domains: list[str],
) -> dict[str, Any] | None:
    """Close an arbitration request when the single owner is unavailable."""

    owner = _arbitration_owner()
    probe = host._agent_availability
    if owner is None or probe is None:
        return None
    try:
        unavailable = frozenset(str(name) for name in probe())
    except Exception:  # noqa: BLE001 - a failed probe never invents unavailability
        host.record_behavior("arbitration_owner_probe_failed")
        return None
    if owner not in unavailable:
        return None
    degradation = evaluate_degradation(set(unavailable) & set(AGENT_DEGRADATION_POLICIES))
    host.record_behavior("arbitration_owner_unavailable")
    verdict = await host._escalate_arbitration(
        correlation_id,
        {"winning_domain": "", "losing_domains": list(domains), "margin": None},
        reason="arbitration_owner_unavailable",
        grounding_extra={
            "arbitration_owner": owner,
            "owner_available": False,
            "degradation_effect": degradation.effects.get(owner, ""),
        },
    )
    return cast(dict[str, Any] | None, verdict)


async def _rehydrate_arbitration_resources(host: Any, store: Any) -> int:
    rows, total = await store.read_state_page(
        "pantheon/forseti/arbitration-resource|",
        limit=_MAX_RESOURCES,
    )
    if total > _MAX_RESOURCES:
        raise RuntimeError("Forseti arbitration resources exceed recovery bound")
    restored = 0
    for row in rows:
        correlation_id = str(row.get("correlation_id") or "")
        resource_id = str(row.get("resource_id") or "")
        if correlation_id and resource_id:
            host._arbitration_resources.set(correlation_id, resource_id)
            restored += 1
    return restored


async def _rehydrate_arbitration_completions(host: Any, store: Any) -> int:
    rows, total = await store.read_state_page(
        "pantheon/forseti/arbitration-completed|",
        limit=_MAX_RESOURCES,
    )
    if total > _MAX_RESOURCES:
        raise RuntimeError("Forseti arbitration completions exceed recovery bound")
    restored = 0
    for row in rows:
        correlation_id = str(row.get("correlation_id") or "")
        if correlation_id:
            host.arbitrations[correlation_id] = str(row.get("outcome") or "completed")
            restored += 1
    return restored


async def _rehydrate_domain_advice(host: Any, store: Any) -> int:
    rows, total = await store.read_state_page(
        "pantheon/forseti/domain-advice|",
        limit=_MAX_RESOURCES,
        field="status",
        value="pending",
    )
    if total > _MAX_RESOURCES:
        raise RuntimeError("Forseti domain advice exceeds recovery bound")
    restored = 0
    for row in rows:
        resource_id = str(row.get("resource_id") or "")
        if not resource_id:
            continue
        advice = row.get("advice")
        impacts = row.get("impacts")
        arguments = row.get("arguments")
        if isinstance(advice, Mapping):
            host._domain_advice.set(resource_id, {str(k): str(v) for k, v in advice.items()})
            restored += 1
        if isinstance(impacts, Mapping):
            host._domain_impact.set(resource_id, {str(k): float(v) for k, v in impacts.items()})
        observed_at = str(row.get("observed_at") or "")
        if observed_at:
            host._domain_observed_at.set(resource_id, observed_at)
        if isinstance(arguments, Mapping):
            host._domain_arguments.set(
                resource_id,
                {
                    str(domain): dict(values)
                    for domain, values in arguments.items()
                    if isinstance(values, Mapping)
                },
            )
    return restored


async def _rehydrate_cross_vertical_completions(host: Any, store: Any) -> int:
    rows, total = await store.read_state_page(
        "pantheon/forseti/cross-vertical-completed|",
        limit=_MAX_RESOURCES,
    )
    if total > _MAX_RESOURCES:
        raise RuntimeError("Forseti completed candidate sets exceed recovery bound")
    restored = 0
    for row in rows:
        correlation_id = str(row.get("correlation_id") or "")
        if correlation_id:
            host._cross_vertical_candidates.mark_completed(correlation_id)
            restored += 1
    return restored


async def _rehydrate_cross_vertical_pending(host: Any, store: Any) -> int:
    rows, total = await store.read_state_page(
        "pantheon/forseti/cross-vertical-pending|",
        limit=_MAX_RESOURCES,
        field="status",
        value="pending",
    )
    if total > _MAX_RESOURCES:
        raise RuntimeError("Forseti pending candidate sets exceed recovery bound")
    restored = 0
    for row in rows:
        correlation_id = str(row.get("correlation_id") or "")
        if not correlation_id or await durable_cross_vertical_completed(host, correlation_id):
            continue
        deadline = datetime.fromisoformat(str(row.get("deadline_at") or ""))
        if deadline.tzinfo is None:
            raise RuntimeError("Forseti cross-vertical deadline is not timezone-aware")
        if host._test_context_clock() >= deadline:
            await mark_cross_vertical_completed(
                host,
                correlation_id,
                "cross_vertical_candidate_timeout",
            )
            await host._close_cross_vertical_candidates(
                (
                    CandidateClosure(
                        correlation_id=correlation_id,
                        resource_id=str(row.get("resource_id") or ""),
                        reason="cross_vertical_candidate_timeout",
                    ),
                )
            )
            restored += 1
            continue
        candidates = row.get("candidates")
        if isinstance(candidates, list):
            for raw in candidates:
                if isinstance(raw, Mapping):
                    host._cross_vertical_candidates.restore_pending(
                        str(raw.get("topic") or ""),
                        dict(raw),
                    )
            start_timeout = getattr(host, "_start_cross_vertical_timeout", None)
            if callable(start_timeout):
                start_timeout(correlation_id)
            else:
                host._cross_vertical_timeout_tasks[correlation_id] = asyncio.create_task(
                    host._expire_cross_vertical_candidates(correlation_id)
                )
            restored += 1
    return restored
