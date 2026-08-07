"""Strict read projection of Muninn-owned detection readiness snapshots."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any, Protocol

from fdai.core.readiness import (
    DETECTION_READINESS_STATE_PREFIX,
    DetectionReadinessDecision,
    DetectionReadinessSnapshot,
)

_MAX_TARGETS = 256


class DetectionReadinessReader(Protocol):
    """Read bounded readiness state records from the authoritative store."""

    async def read_states(self, prefix: str, *, limit: int) -> tuple[Mapping[str, Any], ...]: ...


async def project_detection_readiness(reader: DetectionReadinessReader) -> dict[str, Any]:
    """Decode the current Muninn projection without re-judging it."""

    records = await reader.read_states(DETECTION_READINESS_STATE_PREFIX, limit=_MAX_TARGETS)
    snapshots = [
        DetectionReadinessSnapshot.model_validate(
            {name: record.get(name) for name in DetectionReadinessSnapshot.model_fields}
        )
        for record in records
    ]
    snapshots.sort(key=lambda item: item.resource_ref)
    counts = Counter(item.decision.value for item in snapshots)
    observed_at = max((item.generated_at for item in snapshots), default=None)
    return {
        "source": "muninn-state-snapshot",
        "observed_at": observed_at.isoformat() if observed_at is not None else None,
        "target_count": len(snapshots),
        "counts": {
            decision.value: counts[decision.value] for decision in DetectionReadinessDecision
        },
        "targets": [item.model_dump(mode="json") for item in snapshots],
    }


__all__ = ["DetectionReadinessReader", "project_detection_readiness"]
