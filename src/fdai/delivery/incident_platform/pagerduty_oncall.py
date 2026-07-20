"""PagerDuty on-call roster adapter with explicit Entra identity mapping."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import httpx

from fdai.delivery.incident_platform._common import TokenProvider, request_json, timestamp
from fdai.shared.providers.oncall_schedule import OnCallScheduleError, OnCallShift


@dataclass(frozen=True, slots=True)
class PagerDutyOnCallScheduleConfig:
    rotation_schedule_ids: Mapping[str, str]
    user_oid_map: Mapping[str, str]
    api_base: str = "https://api.pagerduty.com"
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not self.api_base.startswith("https://"):
            raise ValueError("PagerDuty on-call API base MUST use HTTPS")
        if self.timeout_seconds <= 0:
            raise ValueError("PagerDuty on-call timeout MUST be positive")
        if any(
            not key.strip() or not value.strip()
            for key, value in self.rotation_schedule_ids.items()
        ):
            raise ValueError("PagerDuty rotation schedule mappings MUST be non-empty")
        if any(not key.strip() or not value.strip() for key, value in self.user_oid_map.items()):
            raise ValueError("PagerDuty user OID mappings MUST be non-empty")


class PagerDutyOnCallSchedule:
    def __init__(
        self,
        *,
        config: PagerDutyOnCallScheduleConfig,
        token_provider: TokenProvider,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config: Final = config
        self._token_provider = token_provider
        self._http = http_client

    async def current(self, *, rotation: str, at: datetime) -> OnCallShift | None:
        schedule_id = self._config.rotation_schedule_ids.get(rotation)
        if schedule_id is None:
            return None
        if at.tzinfo is None:
            raise OnCallScheduleError("PagerDuty on-call lookup time MUST include timezone")
        payload = await request_json(
            self._http,
            self._token_provider,
            "GET",
            f"{self._config.api_base.rstrip('/')}/oncalls",
            params={
                "schedule_ids[]": schedule_id,
                "since": (at - timedelta(minutes=1)).isoformat(),
                "until": (at + timedelta(minutes=1)).isoformat(),
                "time_zone": "UTC",
                "limit": 100,
            },
            timeout_seconds=self._config.timeout_seconds,
            authorization_scheme="pagerduty-token",
        )
        rows = payload.get("oncalls") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            raise OnCallScheduleError("PagerDuty on-call payload is malformed")
        candidates = sorted(
            (row for row in rows if isinstance(row, Mapping)),
            key=lambda row: int(row.get("escalation_level") or 999),
        )
        mapped: list[tuple[Mapping[str, Any], str]] = []
        for row in candidates:
            user = row.get("user")
            user_id = user.get("id") if isinstance(user, Mapping) else None
            oid = self._config.user_oid_map.get(str(user_id)) if user_id else None
            if oid:
                mapped.append((row, oid))
        if not mapped:
            return None
        primary_row, primary_oid = mapped[0]
        secondary_oid = mapped[1][1] if len(mapped) > 1 else None
        try:
            start = timestamp(primary_row.get("start"), field="start")
            until = timestamp(primary_row.get("end"), field="end")
        except Exception as exc:  # noqa: BLE001 - normalize shared helper errors
            raise OnCallScheduleError("PagerDuty on-call interval is malformed") from exc
        if not start <= at < until:
            return None
        return OnCallShift(
            rotation=rotation,
            primary_oid=primary_oid,
            secondary_oid=secondary_oid,
            start=start,
            until=until,
        )


__all__ = ["PagerDutyOnCallSchedule", "PagerDutyOnCallScheduleConfig"]
