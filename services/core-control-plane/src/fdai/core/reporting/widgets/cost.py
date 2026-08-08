"""Cost-family widget builders: cost_summary, budget_summary.

Both are pure projections; the actual cost / budget numbers come from a
fork-wired datasource (Cost Management adapter, spreadsheet import,
static config).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from fdai.core.reporting.models import DataSet, WidgetSpec


class CostSummaryBuilder:
    """Render a cost breakdown: total + per-group rows.

    Expects rows shaped ``{"group", "amount"}`` (fields overridable via
    ``options``). ``options.currency`` (default ``"USD"``) rides along
    on the payload for the FE to render.
    """

    type_name = "cost_summary"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        group_field = str(spec.options.get("group_field", "group"))
        amount_field = str(spec.options.get("amount_field", "amount"))
        rows: list[dict[str, Any]] = []
        total = 0.0
        for row in data.rows:
            amount = _numeric(row.get(amount_field))
            rows.append({"group": row.get(group_field), "amount": amount})
            if isinstance(amount, (int, float)):
                total += float(amount)
        return {
            "currency": spec.options.get("currency", "USD"),
            "total": total,
            "rows": rows,
        }


class BudgetSummaryBuilder:
    """Budget vs actual with variance and utilization ratio.

    Reads ``options.budget`` and takes the actual value from
    ``DataSet.scalar`` (or the first row's ``amount`` column).
    """

    type_name = "budget_summary"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        budget_raw = _numeric(spec.options.get("budget"))
        budget = 0.0 if not isinstance(budget_raw, (int, float)) else float(budget_raw)
        actual: float
        if data.scalar is not None:
            candidate = _numeric(data.scalar)
            actual = float(candidate) if isinstance(candidate, (int, float)) else 0.0
        elif data.rows:
            candidate = _numeric(data.rows[0].get("amount"))
            actual = float(candidate) if isinstance(candidate, (int, float)) else 0.0
        else:
            actual = 0.0
        variance = actual - budget
        utilization = (actual / budget) if budget != 0 else None
        return {
            "budget": budget,
            "actual": actual,
            "variance": variance,
            "utilization": utilization,
            "currency": spec.options.get("currency", "USD"),
        }


def _numeric(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    # Reject 'nan' / 'inf' string inputs too: float() parses them, but a
    # non-finite amount poisons the total and serializes to invalid JSON.
    return result if math.isfinite(result) else None


__all__ = ["BudgetSummaryBuilder", "CostSummaryBuilder"]
