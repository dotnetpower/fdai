"""Authority-free, current action candidates resolved for registered anomaly signals."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AnomalyActionCandidate:
    """Exact expiring arguments supplied by a server-owned evidence reader, never authority."""

    event_type: str
    resource_ref: str
    action_type: str
    arguments_json: str
    evidence_ref: str
    observed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for text in (self.event_type, self.resource_ref, self.action_type, self.evidence_ref):
            if not text or text != text.strip() or len(text) > 512:
                raise ValueError("anomaly action candidate requires bounded exact identifiers")
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.observed_at, self.expires_at)
        ):
            raise ValueError("anomaly action candidate times must be timezone-aware")
        if not timedelta(0) < self.expires_at - self.observed_at <= timedelta(seconds=300):
            raise ValueError("anomaly action candidate validity must be within 300 seconds")
        self.arguments()

    def arguments(self) -> dict[str, Any]:
        """Return a fresh bounded argument mapping with no caller-mutable shared state."""
        if len(self.arguments_json) > 16_384:
            raise ValueError("anomaly action candidate arguments exceed their bound")
        value = json.loads(self.arguments_json)
        if not isinstance(value, dict) or value.get("target_resource_ref") != self.resource_ref:
            raise ValueError("anomaly action candidate target does not match its arguments")
        if (
            json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
            != self.arguments_json
        ):
            raise ValueError("anomaly action candidate arguments must be canonical JSON")
        return value


class AnomalyActionSource(Protocol):
    """Resolve current, independently verified evidence into an inert exact-target candidate."""

    async def resolve(
        self, *, event_type: str, resource_ref: str
    ) -> AnomalyActionCandidate | None: ...


@dataclass(frozen=True, slots=True)
class AnomalyActionPreparation:
    """Original retained Action reference; preparation can lower but never grant authority."""

    action_id: str
    shadow_only: bool = True
    quorum_required: int = 1

    def __post_init__(self) -> None:
        if str(UUID(self.action_id)) != self.action_id or type(self.shadow_only) is not bool:
            raise ValueError(
                "prepared anomaly Action requires canonical identity and explicit mode"
            )
        if type(self.quorum_required) is not int or not 1 <= self.quorum_required <= 10:
            raise ValueError("prepared anomaly Action requires a bounded approval quorum")


@runtime_checkable
class AnomalyActionPreparer(Protocol):
    """Forseti-owned preparation of immutable original material before approval publication."""

    async def prepare(self, verdict: Mapping[str, Any]) -> AnomalyActionPreparation: ...
