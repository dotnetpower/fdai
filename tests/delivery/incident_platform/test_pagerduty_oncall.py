"""PagerDuty on-call roster identity mapping."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from fdai.delivery.incident_platform import (
    PagerDutyOnCallSchedule,
    PagerDutyOnCallScheduleConfig,
)

_AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


async def _token() -> str:
    return "test-token"


async def test_maps_escalation_order_to_entra_responders() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Token token=test-token"
        return httpx.Response(
            200,
            json={
                "oncalls": [
                    {
                        "escalation_level": 2,
                        "user": {"id": "user-secondary"},
                        "start": "2026-07-20T11:00:00Z",
                        "end": "2026-07-20T13:00:00Z",
                    },
                    {
                        "escalation_level": 1,
                        "user": {"id": "user-primary"},
                        "start": "2026-07-20T11:00:00Z",
                        "end": "2026-07-20T13:00:00Z",
                    },
                ]
            },
        )

    schedule = PagerDutyOnCallSchedule(
        config=PagerDutyOnCallScheduleConfig(
            rotation_schedule_ids={"primary": "schedule-1"},
            user_oid_map={"user-primary": "oid-primary", "user-secondary": "oid-secondary"},
        ),
        token_provider=_token,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    shift = await schedule.current(rotation="primary", at=_AT)
    assert shift is not None
    assert shift.primary_oid == "oid-primary"
    assert shift.secondary_oid == "oid-secondary"


async def test_missing_rotation_or_identity_mapping_returns_no_coverage() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "oncalls": [
                    {
                        "escalation_level": 1,
                        "user": {"id": "unmapped"},
                        "start": "2026-07-20T11:00:00Z",
                        "end": "2026-07-20T13:00:00Z",
                    }
                ]
            },
        )

    schedule = PagerDutyOnCallSchedule(
        config=PagerDutyOnCallScheduleConfig(
            rotation_schedule_ids={"primary": "schedule-1"},
            user_oid_map={},
        ),
        token_provider=_token,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert await schedule.current(rotation="unknown", at=_AT) is None
    assert await schedule.current(rotation="primary", at=_AT) is None
