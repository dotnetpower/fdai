"""Reliability-family widget builders: slo_summary.

Sits by itself for now; a future ``check_status`` / ``monitor_summary``
builder lives here too when we wire those signals.

Widget ``data`` schemas:

- ``slo_summary``: ``{"objective", "attainment", "target", "error_budget",
  "error_budget_remaining", "burn_rate"?, "window"?}``. Every numeric
  field is either a fraction in ``[0, 1]`` or ``None`` (the datasource
  did not supply it).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.reporting.models import DataSet, WidgetSpec


class SloSummaryBuilder:
    """Render one SLO's status card.

    Expects the datasource to return a single row with the keys shown
    below. Missing keys degrade to ``None`` (not zero) so the FE can
    render a "not measured yet" placeholder without inventing zero
    attainment.
    """

    type_name = "slo_summary"

    _FIELDS: tuple[str, ...] = (
        "objective",
        "attainment",
        "target",
        "error_budget",
        "error_budget_remaining",
        "burn_rate",
        "window",
    )

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        del spec
        row: Mapping[str, Any] = data.rows[0] if data.rows else {}
        payload: dict[str, Any] = {field: row.get(field) for field in self._FIELDS}
        payload["measured"] = bool(data.rows)
        return payload


__all__ = ["SloSummaryBuilder"]
