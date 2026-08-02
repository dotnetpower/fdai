"""Promotion-gate projection over durable ActionPromotionRegistry state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.providers.state_store import StateStore


class PersistedPromotionGatesPanel:
    """Render stored promotion metrics without reconstructing shadow verdicts."""

    def __init__(
        self,
        *,
        action_types: Sequence[OntologyActionType],
        store: StateStore,
    ) -> None:
        self._action_types = tuple(action_types)
        self._store = store

    @property
    def path(self) -> str:
        return "/kpi/promotion-gates"

    @property
    def name(self) -> str:
        return "promotion-gates"

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        requested = params.get("action_type")
        action_types = tuple(
            item for item in self._action_types if requested is None or item.name == requested
        )
        rows = [await self._row(action_type) for action_type in action_types]
        return {
            "window_days": None,
            "rows": rows,
            "ready_count": sum(bool(row["ready"]) for row in rows),
            "blocked_count": sum(not bool(row["ready"]) for row in rows),
            "source": "postgres-promotion-state",
            "durable": True,
        }

    async def _row(self, action_type: OntologyActionType) -> Mapping[str, Any]:
        raw = await self._store.read_state(f"action_promotion:{action_type.name}")
        metrics = raw.get("metrics") if isinstance(raw, Mapping) else None
        if not isinstance(metrics, Mapping):
            return {
                "action_type_name": action_type.name,
                "shadow_days_elapsed": 0.0,
                "sample_count": 0,
                "reviewed_count": 0,
                "agreed_count": 0,
                "policy_escapes": 0,
                "accuracy": 0.0,
                "ready": False,
                "gaps": ["no_persisted_promotion_evidence"],
            }
        samples = _non_negative_int(metrics.get("samples"))
        accuracy = _ratio(metrics.get("accuracy"))
        shadow_days = _non_negative_int(metrics.get("shadow_days"))
        policy_escapes = _non_negative_int(metrics.get("policy_escapes"))
        gate = action_type.promotion_gate
        gaps: list[str] = []
        if shadow_days < gate.min_shadow_days:
            gaps.append("insufficient_shadow_days")
        if samples < gate.min_samples:
            gaps.append("insufficient_samples")
        if accuracy < gate.min_accuracy:
            gaps.append("accuracy_below_threshold")
        if policy_escapes > gate.max_policy_escapes:
            gaps.append("policy_escape")
        return {
            "action_type_name": action_type.name,
            "shadow_days_elapsed": float(shadow_days),
            "sample_count": samples,
            "reviewed_count": samples,
            "agreed_count": round(samples * accuracy),
            "policy_escapes": policy_escapes,
            "accuracy": accuracy,
            "ready": not gaps,
            "gaps": gaps,
        }


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def _ratio(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return min(1.0, max(0.0, float(value)))


__all__ = ["PersistedPromotionGatesPanel"]
