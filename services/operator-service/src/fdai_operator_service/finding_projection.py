"""Paginated read-only access to the analyzer's durable current-Finding index."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.finding_state import FINDING_STATE_PREFIX, FindingState
from pydantic import ValidationError

from fdai_operator_service.families.operations import ProjectionQuery, ProjectionUnavailableError

_SQL = """
WITH visible AS (
    SELECT key, value FROM state_kv WHERE key LIKE 'runtime:analyzer-finding-current:%%'
), page AS (
    SELECT key, value FROM visible WHERE key > %s ORDER BY key LIMIT %s
)
SELECT (SELECT COUNT(*) FROM visible) AS total_count,
       COALESCE((SELECT jsonb_agg(value ORDER BY key) FROM page), '[]'::jsonb) AS items
"""


async def read_findings(
    fetch_all: Callable[[str, tuple[object, ...]], Awaitable[list[dict[str, Any]]]],
    query: ProjectionQuery,
) -> Mapping[str, object]:
    """Keep count and page in one database snapshot, without provider calls."""
    cursor = query.cursor
    if cursor is not None and re.fullmatch(r"[a-f0-9]{64}", cursor) is None:
        raise ProjectionUnavailableError("Finding cursor must be an opaque Finding identity")
    limit = min(max(query.limit, 1), 200)
    rows = await fetch_all(_SQL, (FINDING_STATE_PREFIX + (cursor or ""), limit + 1))
    if len(rows) != 1 or not isinstance(rows[0].get("items"), list):
        raise ProjectionUnavailableError("Finding projection returned an invalid page")
    try:
        states = [FindingState.model_validate(value) for value in rows[0]["items"]]
        total = int(rows[0]["total_count"])
    except (ValidationError, TypeError, ValueError, KeyError) as exc:
        raise ProjectionUnavailableError("Finding projection contains invalid state") from exc
    if total < len(states) or len(states) > limit + 1:
        raise ProjectionUnavailableError("Finding projection page count is inconsistent")
    visible = states[:limit]
    return {
        "source": "runtime-observed",
        "observed_at": datetime.now(UTC).isoformat(),
        "total_count": total,
        "items": [state.model_dump(mode="json") for state in visible],
        "next_cursor": visible[-1].finding_id if len(states) > limit else None,
        "execution_authority": False,
    }
