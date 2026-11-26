"""Read-only access to the Console inbox that Core's A2 channel publishes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.console_inbox import CONSOLE_INBOX_PREFIX, ConsoleInboxRecord
from pydantic import ValidationError

from fdai_operator_service.families.operations import ProjectionQuery, ProjectionUnavailableError

_SQL = """
WITH visible AS (
    SELECT key, value, updated_at FROM state_kv WHERE key LIKE 'console-inbox:%%'
), page AS (
    SELECT key, value FROM visible ORDER BY updated_at DESC, key LIMIT %s
)
SELECT (SELECT COUNT(*) FROM visible) AS total_count,
       COALESCE(
           (SELECT jsonb_agg(value ORDER BY key) FROM page),
           '[]'::jsonb
       ) AS items
"""
_DEFAULT_LIMIT = 50


async def read_console_inbox(
    fetch_all: Callable[[str, tuple[object, ...]], Awaitable[list[dict[str, Any]]]],
    query: ProjectionQuery,
) -> Mapping[str, object]:
    """Return the newest bounded alerts, validating every record before it leaves Operator."""
    limit = min(max(query.limit or _DEFAULT_LIMIT, 1), 100)
    rows = await fetch_all(_SQL, (limit,))
    if len(rows) != 1 or not isinstance(rows[0].get("items"), list):
        raise ProjectionUnavailableError("Console inbox projection returned an invalid page")
    try:
        records = [ConsoleInboxRecord.model_validate(value) for value in rows[0]["items"]]
        total = int(rows[0]["total_count"])
    except (ValidationError, TypeError, ValueError, KeyError) as exc:
        raise ProjectionUnavailableError("Console inbox projection contains invalid state") from exc
    if total < len(records) or len(records) > limit:
        raise ProjectionUnavailableError("Console inbox projection page count is inconsistent")
    records.sort(key=lambda item: item.recorded_at, reverse=True)
    return {
        "source": "runtime-observed",
        "observed_at": datetime.now(UTC).isoformat(),
        "total_count": total,
        "items": [record.model_dump(mode="json") for record in records],
        "execution_authority": False,
    }


__all__ = ["CONSOLE_INBOX_PREFIX", "read_console_inbox"]
