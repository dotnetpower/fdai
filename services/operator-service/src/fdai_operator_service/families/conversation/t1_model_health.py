"""Validate Core-owned presentation routing evidence for the chat health view."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError

from .contracts import JsonObject

T1_ROUTING_STATE_KEY = "conversation:t1-mini-routing:v1"
_LOGGER = logging.getLogger(__name__)


class T1RoutingStateStore(Protocol):
    """Read the Core-owned T1 routing state without exposing general projections."""

    async def read_state(self, key: str) -> Mapping[str, object] | None: ...


@dataclass(frozen=True, slots=True)
class T1ModelHealthReader:
    """Read only the durable Core-owned routing projection."""

    store: T1RoutingStateStore

    async def read(self) -> JsonObject:
        payload = await self.store.read_state(T1_ROUTING_STATE_KEY)
        return cast(JsonObject, payload or {})


class _Candidate(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    deployment: str = Field(min_length=1, max_length=128)
    status: Literal["measured", "unmeasured", "failed", "stale"]
    measured_at: str | None
    p50_ms: FiniteFloat | None = Field(ge=0)
    p95_ms: FiniteFloat | None = Field(ge=0)
    samples: int = Field(ge=0, le=8)
    history_ms: list[FiniteFloat] = Field(max_length=8)


class _Router(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    chose: str = Field(max_length=128)
    reason: Literal["latency", "unmeasured", "stale", "unavailable", "disabled"]
    updated_at: str
    expires_at: str
    interval_seconds: int = Field(ge=30, le=3600)
    candidates: list[_Candidate] = Field(min_length=1, max_length=4)


class _Projection(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    schema_version: Literal[1]
    source: Literal["core-t1-mini-routing"]
    execution_authority: Literal[False]
    model: str | None = Field(max_length=128)
    router: _Router


def t1_model_health(value: JsonObject, *, now: datetime | None = None) -> JsonObject:
    """Omit missing/invalid selections and expire speed claims before returning them."""
    if not value:
        return {"model": None}
    try:
        projection = _Projection.model_validate(value)
        router = projection.router
        observed = datetime.fromisoformat(router.updated_at)
        expires = datetime.fromisoformat(router.expires_at)
        current = now if now is not None else datetime.now(UTC)
        if (
            observed.tzinfo is None
            or expires.tzinfo is None
            or observed > current + timedelta(seconds=5)
            or not observed < expires <= observed + timedelta(seconds=2 * router.interval_seconds)
            or router.chose != (projection.model or "")
        ):
            raise ValueError("invalid T1 routing provenance or freshness")
        chosen = next(
            (
                candidate
                for candidate in router.candidates
                if candidate.deployment == projection.model
            ),
            None,
        )
        if router.reason == "latency" and (
            chosen is None or chosen.status != "measured" or chosen.samples == 0
        ):
            raise ValueError("T1 latency selection lacks a measured candidate")
        for candidate in router.candidates:
            if candidate.status == "measured":
                at = datetime.fromisoformat(candidate.measured_at or "")
                if (
                    at.tzinfo is None
                    or not observed - timedelta(seconds=2 * router.interval_seconds)
                    < at
                    <= observed
                    or candidate.samples != len(candidate.history_ms)
                    or candidate.samples == 0
                    or candidate.p50_ms is None
                    or candidate.p95_ms is None
                ):
                    raise ValueError("invalid T1 measurement")
        result = router.model_dump(mode="json")
        chosen_expired = False
        for candidate in result["candidates"]:
            candidate_at = (
                datetime.fromisoformat(candidate["measured_at"])
                if candidate["status"] == "measured"
                else None
            )
            if candidate_at is not None and candidate_at <= current - timedelta(
                seconds=2 * router.interval_seconds
            ):
                candidate["status"] = "stale"
                chosen_expired |= candidate["deployment"] == projection.model
            if candidate["status"] != "measured":
                candidate.update(p50_ms=None, p95_ms=None, samples=0, history_ms=[])
        if current >= expires or chosen_expired:
            result.update(chose="", reason="stale")
            for candidate in result["candidates"]:
                candidate.update(status="stale", p50_ms=None, p95_ms=None, samples=0, history_ms=[])
            return {"model": None, "router": cast(JsonObject, result)}
        return {"model": projection.model, "router": cast(JsonObject, result)}
    except (ValueError, ValidationError):
        _LOGGER.warning("t1_routing_projection_invalid")
        return {"model": None}


__all__ = ["T1ModelHealthReader", "T1_ROUTING_STATE_KEY", "t1_model_health"]
