"""Aggregate audited override use into bounded discovery signals."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from .discovery_contracts import (
    DiscoveryObservationBatch,
    DiscoverySignal,
    DiscoverySignalKind,
)


@dataclass(frozen=True, slots=True)
class OverrideSignalThresholds:
    """Minimum independent scope, dwell, and hit evidence for one signal."""

    min_distinct_scopes: int = 3
    min_dwell_days: int = 14
    min_shadow_hits: int = 100

    def __post_init__(self) -> None:
        if min(self.min_distinct_scopes, self.min_dwell_days, self.min_shadow_hits) < 1:
            raise ValueError("override discovery thresholds MUST be positive")


@dataclass(frozen=True, slots=True)
class OverrideAuditPage:
    """One bounded read of Saga-retained override-resolution audit records."""

    records: tuple[Mapping[str, object], ...]
    complete: bool

    def __post_init__(self) -> None:
        if not isinstance(self.complete, bool):
            raise ValueError("override audit page completeness MUST be boolean")


@runtime_checkable
class OverrideAuditReader(Protocol):
    """Read audit projections without granting audit-write authority."""

    async def list_override_resolutions(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        limit: int,
    ) -> OverrideAuditPage: ...


class OverrideDiscoverySignalSource:
    """Produce one inert signal per rule whose audited overrides clear every bar."""

    def __init__(
        self,
        *,
        reader: OverrideAuditReader,
        thresholds: OverrideSignalThresholds | None = None,
    ) -> None:
        self._reader = reader
        self._thresholds = thresholds or OverrideSignalThresholds()

    async def observe(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        limit: int,
    ) -> DiscoveryObservationBatch:
        if window_start.tzinfo is None or window_end.tzinfo is None:
            raise ValueError("override discovery window MUST be timezone-aware")
        if window_end < window_start or limit < 1:
            raise ValueError("override discovery window and limit MUST be valid")
        page = await self._reader.list_override_resolutions(
            window_start=window_start,
            window_end=window_end,
            limit=limit,
        )
        if len(page.records) > limit:
            raise ValueError("override audit reader exceeded its record limit")
        observations = tuple(_parse_record(record) for record in page.records)
        signals = tuple(
            signal
            for rule_id in sorted({item.rule_id for item in observations})
            if (
                signal := _signal_for(
                    rule_id,
                    tuple(item for item in observations if item.rule_id == rule_id),
                    self._thresholds,
                )
            )
            is not None
        )
        return DiscoveryObservationBatch(
            window_start=window_start.astimezone(UTC),
            window_end=window_end.astimezone(UTC),
            signals=signals,
            complete=page.complete,
        )


@dataclass(frozen=True, slots=True)
class _OverrideObservation:
    rule_id: str
    override_id: str
    scope: str
    mode: str
    recorded_at: datetime
    evidence_ref: str


def _parse_record(record: Mapping[str, object]) -> _OverrideObservation:
    if record.get("action_kind") != "governance.override_resolved":
        raise ValueError("override discovery accepts override-resolution audit records only")
    required = ("rule_id", "override_id", "override_scope", "override_mode", "recorded_at")
    values = {key: record.get(key) for key in required}
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise ValueError("override-resolution audit record is incomplete")
    recorded_at = datetime.fromisoformat(str(values["recorded_at"]).replace("Z", "+00:00"))
    if recorded_at.tzinfo is None:
        raise ValueError("override-resolution audit time MUST be timezone-aware")
    material = {
        key: record.get(key)
        for key in (
            "event_id",
            "idempotency_key",
            "rule_id",
            "override_id",
            "override_scope",
            "override_mode",
            "recorded_at",
        )
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    return _OverrideObservation(
        rule_id=str(values["rule_id"]),
        override_id=str(values["override_id"]),
        scope=str(values["override_scope"]),
        mode=str(values["override_mode"]),
        recorded_at=recorded_at.astimezone(UTC),
        evidence_ref=f"audit:sha256:{digest}",
    )


def _signal_for(
    rule_id: str,
    observations: tuple[_OverrideObservation, ...],
    thresholds: OverrideSignalThresholds,
) -> DiscoverySignal | None:
    distinct_scopes = {item.scope.casefold() for item in observations}
    first = min(item.recorded_at for item in observations)
    last = max(item.recorded_at for item in observations)
    dwell_days = math.floor((last - first).total_seconds() / 86400)
    if (
        len(distinct_scopes) < thresholds.min_distinct_scopes
        or dwell_days < thresholds.min_dwell_days
        or len(observations) < thresholds.min_shadow_hits
    ):
        return None
    modes = Counter(item.mode for item in observations)
    identity = hashlib.sha256(
        json.dumps(
            {
                "rule_id": rule_id,
                "scopes": sorted(distinct_scopes),
                "first": first.isoformat(),
                "last": last.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return DiscoverySignal(
        signal_id=f"override-{identity}",
        kind=DiscoverySignalKind.OVERRIDE,
        observed_at=last,
        evidence_refs=tuple(sorted({item.evidence_ref for item in observations}))[:64],
        facts={
            "rule_id": rule_id,
            "distinct_scope_count": len(distinct_scopes),
            "dwell_days": dwell_days,
            "shadow_hit_count": len(observations),
            "mode_counts": dict(sorted(modes.items())),
        },
    )


__all__ = [
    "OverrideAuditPage",
    "OverrideAuditReader",
    "OverrideDiscoverySignalSource",
    "OverrideSignalThresholds",
]
