"""Resolve causal intervention receipts against Thor's durable ActionRun records.

A causal hypothesis closes as confirmed only when an independent observation follows an
intervention that Thor actually executed and verified. This resolver reads Thor's single-writer
ActionRun record and accepts the receipt only when the run declared the same hypothesis before
execution, left shadow mode, succeeded, and carries the exact verified effect receipt. It never
grants execution, approval, or promotion authority; every missing or inconsistent fact returns
``False`` so closure stays inconclusive.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.core.rca.runtime import CausalClosureObservation
from fdai.shared.providers.state_store import StateStore

_VERIFIED_STATES = frozenset({"succeeded"})


@dataclass(frozen=True, slots=True)
class StateStoreCausalInterventionReceiptVerifier:
    """Accept one closure receipt only from Thor's exact verified ActionRun."""

    store: StateStore
    run_prefix: str = "thor:run|"

    async def verify(self, observation: CausalClosureObservation) -> bool:
        action_ref = observation.intervention_action_ref
        receipt = observation.intervention_receipt_digest
        executed_at = observation.intervention_executed_at
        if not action_ref or receipt is None or executed_at is None:
            return False
        raw_run = await self.store.read_state(f"{self.run_prefix}{action_ref}")
        if not isinstance(raw_run, Mapping):
            return False
        params = raw_run.get("params")
        if not isinstance(params, Mapping):
            return False
        verified_at = _aware_time(raw_run.get("effect_verified_at"))
        receipts = {
            value
            for value in (
                raw_run.get("execution_closure_ref"),
                raw_run.get("effect_verification_ref"),
            )
            if isinstance(value, str) and value
        }
        return (
            raw_run.get("correlation_id") == action_ref
            and str(raw_run.get("state") or "") in _VERIFIED_STATES
            and raw_run.get("shadow_mode") is False
            and params.get("causal_hypothesis_ref") == observation.hypothesis.hypothesis_id
            and receipt in receipts
            and verified_at is not None
            and executed_at <= verified_at <= observation.observed_at
        )


def _aware_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


__all__ = ["StateStoreCausalInterventionReceiptVerifier"]
