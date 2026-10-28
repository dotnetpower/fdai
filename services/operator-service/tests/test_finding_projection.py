from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fdai.core.readiness.finding_state import FindingState, finding_identity
from fdai.shared.contracts.models import Severity
from fdai_operator_service.families.operations import ProjectionQuery, ProjectionUnavailableError
from fdai_operator_service.finding_projection import read_findings


def query(cursor: str | None = None) -> ProjectionQuery:
    return ProjectionQuery(
        operation="finding.list",
        principal_id="reader:test",
        path={},
        params={},
        limit=2,
        cursor=cursor,
    )


async def test_empty_page_is_explicit_and_never_grants_authority() -> None:
    fetch = AsyncMock(return_value=[{"total_count": 0, "items": []}])
    result = await read_findings(fetch, query())
    assert result["total_count"] == 0
    assert result["next_cursor"] is None
    assert result["items"] == []
    assert result["execution_authority"] is False
    assert fetch.call_args.args[1] == ("runtime:analyzer-finding-current:", 3)


@pytest.mark.parametrize("cursor", ["../scope", "x" * 64, "'; SELECT secret", ""])
async def test_invalid_cursor_never_reaches_database(cursor: str) -> None:
    fetch = AsyncMock()
    with pytest.raises(ProjectionUnavailableError, match="cursor"):
        await read_findings(fetch, query(cursor))
    fetch.assert_not_awaited()


async def test_invalid_finding_is_unavailable_not_an_empty_success() -> None:
    fetch = AsyncMock(return_value=[{"total_count": 1, "items": [{"status": "active"}]}])
    with pytest.raises(ProjectionUnavailableError, match="invalid state"):
        await read_findings(fetch, query())


def finding(resource_ref: str) -> dict[str, object]:
    at = datetime(2026, 9, 1, tzinfo=UTC)
    return FindingState(
        finding_id=finding_identity("virtual_machine", resource_ref, "host_cpu"),
        revision=1,
        notification_version=1,
        notification_reason="opened",
        notification_changed_at=at,
        resource_ref=resource_ref,
        resource_kind="virtual_machine",
        signal="host_cpu",
        severity=Severity.HIGH,
        status="active",
        observation="CPU exceeded its configured threshold.",
        observation_key="observation:test",
        observation_digest="a" * 64,
        first_seen_at=at,
        occurred_at=at,
        recorded_at=at,
        current_state="cpu_threshold_observed",
        evidence_complete=True,
        evidence_state="observed",
        recovery_closed=False,
        assessed_by="core.investigation.host_cpu",
        evidence_refs=("metric:test",),
        evidence_gaps=(),
        publication="published",
    ).model_dump(mode="json")


async def test_valid_pages_preserve_total_and_use_last_visible_identity_as_cursor() -> None:
    states = sorted(
        [finding("resource:vm-a"), finding("resource:vm-b"), finding("resource:vm-c")],
        key=lambda state: str(state["finding_id"]),
    )
    fetch = AsyncMock(
        side_effect=[
            [{"total_count": 3, "items": states}],
            [{"total_count": 3, "items": states[2:]}],
        ]
    )
    first = await read_findings(fetch, query())
    assert first["items"] == states[:2]
    assert first["total_count"] == 3
    assert first["source"] == "runtime-observed"
    assert first["execution_authority"] is False
    assert first["next_cursor"] == states[1]["finding_id"]

    cursor = str(first["next_cursor"])
    last = await read_findings(fetch, query(cursor))
    assert last["items"] == states[2:]
    assert last["total_count"] == 3
    assert last["next_cursor"] is None
    assert fetch.call_args.args[1] == ("runtime:analyzer-finding-current:" + cursor, 3)


@pytest.mark.parametrize("total,items", [(0, 1), (10, 4)])
async def test_inconsistent_page_is_unavailable(total: int, items: int) -> None:
    fetch = AsyncMock(
        return_value=[{"total_count": total, "items": [finding("resource:vm")] * items}]
    )
    with pytest.raises(ProjectionUnavailableError, match="count"):
        await read_findings(fetch, query())
