"""Read and render retained chaos experiment outcomes without execution authority."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

from fdai_operator_service.families.operations.contracts import ProjectionUnavailableError
from fdai_operator_service.postgres_dsn import normalize_psycopg_dsn

REPORT_ID = "chaos-enforce-results"
_REPORT_NAME = "Chaos Enforce Results"
_REPORT_DESCRIPTION = (
    "Measured fault-injection detection and rollback outcomes retained by the report signal feed."
)
_REPORT_TAGS = ("resilience", "chaos", "measured")
_ALLOWED_OUTCOMES = frozenset(
    {
        "validated",
        "not_detected",
        "aborted",
        "blast_radius_exceeded",
        "rollback_failed",
        "shadowed",
    }
)
_ALLOWED_SEVERITIES = frozenset({"critical", "high", "medium", "low"})
_ALLOWED_MODES = frozenset({"shadow", "enforce"})

_CHAOS_RESULTS_SQL = """
SELECT signal_id, severity, resource_ref, occurred_at,
       scenario_id, outcome, mode, expected_signal,
       detected, reverted, injected, stopped, approval_ref
  FROM operator_chaos_report_signal
 WHERE occurred_at >= %(since)s
   AND occurred_at <= %(until)s
 ORDER BY occurred_at DESC, signal_id
 LIMIT %(limit)s
"""


@dataclass(frozen=True, slots=True)
class ChaosResult:
    signal_id: str
    severity: str
    resource_ref: str
    occurred_at: datetime
    scenario_id: str
    outcome: str
    mode: str
    expected_signal: str
    detected: bool
    reverted: bool
    injected: bool
    stopped: bool
    approval_ref: str


class ChaosResultReader(Protocol):
    async def list_results(
        self, *, since: datetime, until: datetime, limit: int
    ) -> Sequence[ChaosResult]: ...


@dataclass(frozen=True, slots=True)
class PostgresChaosResultReaderConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn.strip():
            raise ValueError("PostgresChaosResultReaderConfig.dsn must be non-empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresChaosResultReaderConfig timeouts must be positive")


class PostgresChaosResultReader:
    """Read the Operator-owned security-barrier view only."""

    def __init__(self, config: PostgresChaosResultReaderConfig) -> None:
        self._config = config

    async def list_results(
        self, *, since: datetime, until: datetime, limit: int
    ) -> Sequence[ChaosResult]:
        if since.tzinfo is None or until.tzinfo is None or since > until:
            raise ValueError("chaos result window must be ordered and timezone-aware")
        if not 1 <= limit <= 500:
            raise ValueError("chaos result limit must be between 1 and 500")
        try:
            async with await psycopg.AsyncConnection.connect(
                normalize_psycopg_dsn(self._config.dsn),
                connect_timeout=self._config.connect_timeout_s,
                row_factory=dict_row,
            ) as connection:
                timeout_ms = int(self._config.statement_timeout_ms)
                await connection.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
                cursor = await connection.execute(
                    _CHAOS_RESULTS_SQL,
                    {"since": since, "until": until, "limit": limit},
                )
                rows = await cursor.fetchall()
            return tuple(_decode_row(row) for row in rows)
        except (psycopg.Error, TypeError, ValueError) as exc:
            raise ProjectionUnavailableError(
                "authoritative chaos result projection is unavailable"
            ) from exc


def report_summary() -> Mapping[str, object]:
    return {
        "id": REPORT_ID,
        "version": "1.0.0",
        "name": _REPORT_NAME,
        "description": _REPORT_DESCRIPTION,
        "tags": list(_REPORT_TAGS),
        "widget_count": 5,
        "datasources": ["chaos_results"],
        "variables": [
            {
                "name": "window_days",
                "default": "7",
                "values": ["1", "7", "30"],
                "description": "Measured result window in days.",
            }
        ],
    }


def registry_source() -> Mapping[str, object]:
    return {
        "datasource": "chaos_results",
        "source": "operator_chaos_report_signal",
        "availability": "available",
        "synthetic": False,
        "as_of": None,
    }


async def render_report(
    reader: ChaosResultReader,
    *,
    window_days: int,
    now: datetime | None = None,
) -> Mapping[str, object]:
    if window_days not in {1, 7, 30}:
        raise ValueError("window_days must be one of 1, 7, or 30")
    until = now or datetime.now(UTC)
    since = until - timedelta(days=window_days)
    results = tuple(await reader.list_results(since=since, until=until, limit=500))
    outcome_counts = {
        outcome: sum(result.outcome == outcome for result in results)
        for outcome in sorted(_ALLOWED_OUTCOMES)
    }
    rows = [
        {
            "scenario": result.scenario_id,
            "outcome": result.outcome,
            "detected": result.detected,
            "reverted": result.reverted,
            "severity": result.severity,
            "target": result.resource_ref,
            "expected_signal": result.expected_signal,
            "at": result.occurred_at.isoformat(),
        }
        for result in results
    ]
    widgets: list[Mapping[str, object]] = [
        _value_widget("experiments", "Experiments", len(results), "runs"),
        _value_widget("validated", "Validated", outcome_counts.get("validated", 0), "runs"),
        _value_widget(
            "detection-gaps",
            "Detection gaps",
            outcome_counts.get("not_detected", 0),
            "runs",
        ),
        _value_widget(
            "rollback-failures",
            "Rollback failures",
            outcome_counts.get("rollback_failed", 0),
            "runs",
        ),
        {
            "id": "experiment-results",
            "type": "table",
            "title": "Measured experiment results",
            "data": {
                "columns": [
                    "scenario",
                    "outcome",
                    "detected",
                    "reverted",
                    "severity",
                    "target",
                    "expected_signal",
                    "at",
                ],
                "rows": rows,
                "total_rows": len(rows),
            },
            "options": {},
        },
    ]
    latest = results[0].occurred_at.isoformat() if results else None
    return {
        "id": REPORT_ID,
        "version": "1.0.0",
        "name": _REPORT_NAME,
        "description": _REPORT_DESCRIPTION,
        "generated_at": until.isoformat(),
        "time_range": {"from": since.isoformat(), "to": until.isoformat()},
        "variables": {"window_days": str(window_days)},
        "widgets": widgets,
        "tags": list(_REPORT_TAGS),
        "provenance": {
            "availability": "available",
            "synthetic": False,
            "sources": [
                {
                    **registry_source(),
                    "as_of": latest,
                }
            ],
        },
    }


def _value_widget(widget_id: str, title: str, value: int, unit: str) -> Mapping[str, object]:
    return {
        "id": widget_id,
        "type": "query_value",
        "title": title,
        "data": {"value": value, "unit": unit},
        "options": {"unit": unit},
    }


def _decode_row(row: Mapping[str, Any]) -> ChaosResult:
    severity = _required_text(row, "severity")
    outcome = _required_text(row, "outcome")
    mode = _required_text(row, "mode")
    if severity not in _ALLOWED_SEVERITIES:
        raise ValueError("chaos result severity is unsupported")
    if outcome not in _ALLOWED_OUTCOMES:
        raise ValueError("chaos result outcome is unsupported")
    if mode not in _ALLOWED_MODES:
        raise ValueError("chaos result mode is unsupported")
    occurred_at = row.get("occurred_at")
    if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
        raise ValueError("chaos result occurred_at is invalid")
    return ChaosResult(
        signal_id=_required_text(row, "signal_id"),
        severity=severity,
        resource_ref=_required_text(row, "resource_ref"),
        occurred_at=occurred_at,
        scenario_id=_required_text(row, "scenario_id"),
        outcome=outcome,
        mode=mode,
        expected_signal=_required_text(row, "expected_signal"),
        detected=_required_bool(row, "detected"),
        reverted=_required_bool(row, "reverted"),
        injected=_required_bool(row, "injected"),
        stopped=_required_bool(row, "stopped"),
        approval_ref=_required_text(row, "approval_ref"),
    )


def _required_text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError(f"chaos result {key} is invalid")
    return value


def _required_bool(row: Mapping[str, Any], key: str) -> bool:
    value = row.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"chaos result {key} is invalid")
    return value


__all__ = [
    "ChaosResult",
    "ChaosResultReader",
    "PostgresChaosResultReader",
    "PostgresChaosResultReaderConfig",
    "REPORT_ID",
    "registry_source",
    "render_report",
    "report_summary",
]
