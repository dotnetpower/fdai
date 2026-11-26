"""Immutable Thor dispatch-entry observations, not effect or coverage evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from fdai.agents._framework.action_run_identity import action_run_identity_digest
from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.thor_action_run import ActionRun
from fdai.shared.providers.state_store import StateStore

DISPATCH_START_PREFIX = "thor:dispatch-start:v1|"


@runtime_checkable
class DispatchStartRecorder(Protocol):
    async def record_dispatch_start(
        self,
        run: ActionRun,
        *,
        started_at: datetime,
        resource_lock_ref: str | None,
    ) -> None: ...


class StateStoreDispatchStartRecorder:
    """Persist the first observation without changing canonical ActionRun state."""

    store: StateStore

    async def record_dispatch_start(
        self,
        run: ActionRun,
        *,
        started_at: datetime,
        resource_lock_ref: str | None,
    ) -> None:
        record = dispatch_start_record(
            run, started_at=started_at, resource_lock_ref=resource_lock_ref
        )
        key = dispatch_start_key(run.correlation_id)
        if await self.store.write_state_if_absent(key, record):
            return
        retained = await self.store.read_state(key)
        if retained is None:
            raise RuntimeError("retained dispatch observation is unavailable")
        validate_retained_dispatch_start(retained, record)


def dispatch_start_key(correlation_id: str) -> str:
    return DISPATCH_START_PREFIX + hashlib.sha256(correlation_id.encode("utf-8")).hexdigest()


def dispatch_start_record(
    run: ActionRun, *, started_at: datetime, resource_lock_ref: str | None
) -> dict[str, object]:
    if run.shadow_mode or run.state is not ActionRunState.EXECUTING:
        raise ValueError("dispatch observation requires an executing non-shadow ActionRun")
    if started_at.utcoffset() is None:
        raise ValueError("dispatch observation timestamp must be timezone-aware")
    if not run.correlation_id or not run.resource_id or not run.idempotency_key:
        raise ValueError("dispatch observation requires exact execution identity")
    return {
        "schema_version": "1.0.0",
        "kind": "thor.dispatch_entry",
        "owner_agent": "Thor",
        "correlation_id": run.correlation_id,
        "action_run_identity": action_run_identity_digest(run.to_dict()),
        "action_type": run.action_type,
        "resource_id": run.resource_id,
        "idempotency_digest": hashlib.sha256(run.idempotency_key.encode("utf-8")).hexdigest(),
        "dispatch_started_at": started_at.astimezone(UTC).isoformat(),
        "resource_lock_ref": resource_lock_ref,
        "execution_audit_receipt": run.execution_audit_receipt,
        "execution_authority": False,
        "effect_verified": False,
        "history_complete": False,
    }


def validate_retained_dispatch_start(
    retained: Mapping[str, object], candidate: Mapping[str, object]
) -> None:
    if set(retained) != set(candidate) or any(
        type(retained[key]) is not type(value) or retained[key] != value
        for key, value in candidate.items()
        if key != "dispatch_started_at"
    ):
        raise RuntimeError("retained dispatch observation conflicts with execution identity")
    value = retained["dispatch_started_at"]
    if not isinstance(value, str):
        raise RuntimeError("retained dispatch observation timestamp is invalid")
    try:
        prior = datetime.fromisoformat(value)
        current = datetime.fromisoformat(str(candidate["dispatch_started_at"]))
    except ValueError as exc:
        raise RuntimeError("retained dispatch observation timestamp is invalid") from exc
    if prior.utcoffset() is None or prior > current:
        raise RuntimeError("retained dispatch observation timestamp is not causal")
