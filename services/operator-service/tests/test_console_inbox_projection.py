from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fdai_operator_service.console_inbox_projection import read_console_inbox
from fdai_operator_service.families.operations import ProjectionQuery, ProjectionUnavailableError


def query(limit: int = 50) -> ProjectionQuery:
    return ProjectionQuery(
        operation="notification.inbox",
        principal_id="reader:test",
        path={},
        params={},
        limit=limit,
        cursor=None,
    )


def record(index: int, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1.0.0",
        "inbox_id": f"{index:032x}",
        "category": "operational_alert",
        "trust_tier": "a2_operational_alert",
        "severity": "error",
        "title": f"Alert {index}",
        "body": "Bounded body.",
        "correlation_id": f"correlation-{index}",
        "audit_id": f"audit-{index}",
        "recorded_at": f"2026-10-29T00:00:0{index}+00:00",
        "execution_authority": False,
    }
    value.update(overrides)
    return value


async def test_empty_inbox_is_an_explicit_no_authority_success() -> None:
    fetch = AsyncMock(return_value=[{"total_count": 0, "items": []}])

    result = await read_console_inbox(fetch, query())

    assert result["items"] == []
    assert result["total_count"] == 0
    assert result["source"] == "runtime-observed"
    assert result["execution_authority"] is False
    assert fetch.call_args.args[1] == (50,)


async def test_records_are_validated_and_returned_newest_first() -> None:
    fetch = AsyncMock(return_value=[{"total_count": 3, "items": [record(1), record(3), record(2)]}])

    result = await read_console_inbox(fetch, query())

    assert [item["title"] for item in result["items"]] == ["Alert 3", "Alert 2", "Alert 1"]  # type: ignore[index, union-attr]


@pytest.mark.parametrize(
    "bad",
    [
        record(1, execution_authority=True),
        record(1, trust_tier="a1_hil_approval"),
        record(1, severity="verbose"),
        record(1, unexpected="field"),
    ],
)
async def test_invalid_record_is_unavailable_not_an_empty_success(bad: dict[str, object]) -> None:
    fetch = AsyncMock(return_value=[{"total_count": 1, "items": [bad]}])

    with pytest.raises(ProjectionUnavailableError, match="invalid state"):
        await read_console_inbox(fetch, query())


async def test_inconsistent_page_is_unavailable_and_the_limit_is_bounded() -> None:
    fetch = AsyncMock(return_value=[{"total_count": 0, "items": [record(1)]}])
    with pytest.raises(ProjectionUnavailableError, match="inconsistent"):
        await read_console_inbox(fetch, query())

    fetch = AsyncMock(return_value=[{"total_count": 0, "items": []}])
    await read_console_inbox(fetch, query(limit=10_000))
    assert fetch.call_args.args[1] == (100,)
