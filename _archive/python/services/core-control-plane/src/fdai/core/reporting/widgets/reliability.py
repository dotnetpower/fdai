"""Reliability-family widget builders: slo_summary, alert_status,
check_status, service_summary, flame_graph.

Widget ``data`` schemas:

- ``slo_summary``: ``{"objective", "attainment", "target", "error_budget",
  "error_budget_remaining", "burn_rate"?, "window"?}``. Every numeric
  field is either a fraction in ``[0, 1]`` or ``None`` (the datasource
  did not supply it).
- ``alert_status``: ``{"active": [{"id", "severity", "title"}],
  "counts_by_severity": {"critical": n, ...}}``.
- ``check_status``: ``{"checks": [{"name", "status", "message"?}],
  "summary": {"ok": n, "warn": n, "fail": n}}``.
- ``service_summary``: ``{"service", "red": {"requests_rps",
  "error_rate", "latency_p50", "latency_p99"}, "health"}``.
- ``flame_graph``: ``{"root": {name, value, children: [...]}}``.
"""

from __future__ import annotations

import math
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


_KNOWN_SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low", "info")
_KNOWN_CHECK_STATUSES: tuple[str, ...] = ("ok", "warn", "fail", "unknown")
_KNOWN_HEALTHS: frozenset[str] = frozenset({"healthy", "degraded", "unhealthy", "unknown"})


class AlertStatusBuilder:
    """Roll active alerts up by severity and expose the raw list."""

    type_name = "alert_status"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        del spec
        counts = dict.fromkeys(_KNOWN_SEVERITIES, 0)
        active: list[dict[str, Any]] = []
        for row in data.rows:
            severity = str(row.get("severity", "info")).lower()
            if severity not in counts:
                severity = "info"
            counts[severity] += 1
            active.append(
                {
                    "id": row.get("id"),
                    "severity": severity,
                    "title": row.get("title"),
                    "resource": row.get("resource"),
                    "at": row.get("at"),
                }
            )
        return {"active": active, "counts_by_severity": counts, "total": len(active)}


class CheckStatusBuilder:
    """Render a health-check grid + ok/warn/fail summary."""

    type_name = "check_status"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        del spec
        summary = dict.fromkeys(_KNOWN_CHECK_STATUSES, 0)
        checks: list[dict[str, Any]] = []
        for row in data.rows:
            status = str(row.get("status", "unknown")).lower()
            if status not in summary:
                status = "unknown"
            summary[status] += 1
            checks.append(
                {
                    "name": row.get("name"),
                    "status": status,
                    "message": row.get("message"),
                    "at": row.get("at"),
                }
            )
        return {"checks": checks, "summary": summary}


class ServiceSummaryBuilder:
    """Render a single service's RED metrics + coarse health label.

    Expects a single row with ``service`` / ``requests_rps`` /
    ``error_rate`` / ``latency_p50`` / ``latency_p99`` / ``health``
    fields (missing fields degrade to ``None``).
    """

    type_name = "service_summary"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        del spec
        row: Mapping[str, Any] = data.rows[0] if data.rows else {}
        health = str(row.get("health", "unknown")).lower()
        if health not in _KNOWN_HEALTHS:
            health = "unknown"
        return {
            "service": row.get("service"),
            "red": {
                "requests_rps": row.get("requests_rps"),
                "error_rate": row.get("error_rate"),
                "latency_p50": row.get("latency_p50"),
                "latency_p99": row.get("latency_p99"),
            },
            "health": health,
            "measured": bool(data.rows),
        }


class FlameGraphBuilder:
    """Render a nested flame graph.

    Expects rows shaped ``{"name", "value", "parent"?}``. Rows with
    ``parent=None`` (or missing) become root frames; other rows attach
    under their parent by name. Duplicate ``name`` values are summed
    into the same node (single-stack assumption). This is the
    CSP-neutral equivalent of the profiling flame-graph shape.
    """

    type_name = "flame_graph"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        del spec
        nodes: dict[str, dict[str, Any]] = {}
        parent_of: dict[str, str] = {}
        for row in data.rows:
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            node = nodes.setdefault(name, {"name": name, "value": 0.0, "children": []})
            try:
                value = float(row.get("value") or 0)
            except (TypeError, ValueError):
                value = 0.0
            if math.isfinite(value):
                node["value"] += value
            parent = row.get("parent")
            if parent is None:
                continue
            parent_name = str(parent).strip()
            # Skip a self-parent edge (a 1-cycle). First declared parent
            # wins so the tree is deterministic across row order.
            if not parent_name or parent_name == name:
                continue
            nodes.setdefault(parent_name, {"name": parent_name, "value": 0.0, "children": []})
            parent_of.setdefault(name, parent_name)
        # Attach children, skipping any edge that would close a cycle, so
        # the emitted structure is always a forest of trees. A cyclic
        # parent chain (A->B->A) would otherwise build a self-referential
        # object that raises ``ValueError: Circular reference`` at
        # ``json.dumps`` time - OUTSIDE the engine's per-widget isolation,
        # failing the whole report.
        child_names: set[str] = set()
        for child_name, parent_name in parent_of.items():
            if _closes_cycle(child_name, parent_name, parent_of):
                continue
            nodes[parent_name]["children"].append(nodes[child_name])
            child_names.add(child_name)
        return {"roots": [node for name, node in nodes.items() if name not in child_names]}


def _closes_cycle(child: str, parent: str, parent_of: Mapping[str, str]) -> bool:
    """True when attaching ``child`` under ``parent`` would form a cycle.

    Walks the parent chain up from ``parent``; if it reaches ``child``
    (or revisits a node) the edge would close a loop and MUST be dropped.
    """
    seen: set[str] = set()
    cursor: str | None = parent
    while cursor is not None:
        if cursor == child or cursor in seen:
            return True
        seen.add(cursor)
        cursor = parent_of.get(cursor)
    return False


__all__ = [
    "AlertStatusBuilder",
    "CheckStatusBuilder",
    "FlameGraphBuilder",
    "ServiceSummaryBuilder",
    "SloSummaryBuilder",
]
