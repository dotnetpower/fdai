"""Project durable audit evidence into the production FinOps summary.

This read-only module owns no route, authorization, persistence, approval, or
execution behavior; provenance remains supplied by the Operator API read model.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.verticals.cost_governance.finops import FinOpsActionKind
from fdai.delivery.operator_api.read_model import AuditQueryFilters, ConsoleReadModel

_FINOPS_ACTION_KINDS = frozenset(kind.value for kind in FinOpsActionKind)


class AuditFinOpsPanel:
    """Project recorded cost actions and savings without estimating missing values."""

    def __init__(self, read_model: ConsoleReadModel, *, window_days: int = 30) -> None:
        self._read_model = read_model
        self._window_days = window_days

    @property
    def path(self) -> str:
        return "/finops"

    @property
    def name(self) -> str:
        return "finops"

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        del params
        page = await self._read_model.list_audit(
            limit=500,
            filters=AuditQueryFilters(window_days=self._window_days),
        )
        by_kind: dict[str, int] = {}
        total_actions = 0
        estimated_monthly_savings = 0.0
        for item in page.items:
            if item.action_kind not in _FINOPS_ACTION_KINDS:
                continue
            total_actions += 1
            by_kind[item.action_kind] = by_kind.get(item.action_kind, 0) + 1
            savings = item.entry.get("estimated_savings")
            if isinstance(savings, (int, float)) and not isinstance(savings, bool):
                estimated_monthly_savings += float(savings)
        return {
            "vertical": "finops",
            "total_actions": total_actions,
            "by_kind": by_kind,
            "estimated_monthly_savings": round(estimated_monthly_savings, 2),
            "sampled_events": len(page.items),
            "source": "postgres-audit",
            "durable": True,
            "window_days": self._window_days,
            "as_of": page.items[0].recorded_at if page.items else None,
        }


__all__ = ["AuditFinOpsPanel"]
