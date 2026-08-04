"""Reader-only Dynamic model and trajectory assurance projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai.shared.providers.state_store import StateStore

_MODEL_PREFIXES = {
    "scalar_active": "dynamic-effect-model:active:",
    "scalar_challenger": "dynamic-effect-model:challenger:",
    "graph_active": "dynamic-graph-effect-model:active:",
    "graph_challenger": "dynamic-graph-effect-model:challenger:",
}
_TRAJECTORY_PREFIX = "dynamic-trajectory-episode:"
_MAX_RECORDS = 1000


class DynamicAssurancePanel:
    path = "/dynamic-assurance"
    name = "dynamic-assurance"

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, object]:
        del params
        model_groups: dict[str, object] = {}
        truncated = False
        for name, prefix in _MODEL_PREFIXES.items():
            rows = await self._store.read_states(prefix, limit=_MAX_RECORDS)
            model_groups[name] = _model_summary(rows)
            truncated = truncated or len(rows) >= _MAX_RECORDS
        trajectories = await self._store.read_states(_TRAJECTORY_PREFIX, limit=_MAX_RECORDS)
        trajectory_counts = {"open": 0, "closed": 0, "unknown": 0}
        for row in trajectories:
            status = row.get("status")
            key = status if status in {"open", "closed"} else "unknown"
            trajectory_counts[key] += 1
        truncated = truncated or len(trajectories) >= _MAX_RECORDS
        return {
            "source": "state-store",
            "durable": True,
            "authority": "read-only-evidence",
            "models": model_groups,
            "trajectories": {
                "total": len(trajectories),
                **trajectory_counts,
            },
            "truncated": truncated,
        }


def _model_summary(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, object]:
    samples = [int(row.get("sample_count", 0)) for row in rows]
    errors = [float(row.get("mean_absolute_error", 0.0)) for row in rows]
    refs = [reference for row in rows if (reference := _model_ref(row)) is not None]
    return {
        "count": len(rows),
        "sample_count": sum(samples),
        "max_mean_absolute_error": max(errors, default=None),
        "model_refs": sorted(refs)[:100],
    }


def _model_ref(row: Mapping[str, Any]) -> str | None:
    model_id = row.get("model_id")
    version = row.get("version")
    revision = row.get("revision")
    if (
        not isinstance(model_id, str)
        or not isinstance(version, str)
        or not isinstance(revision, int)
    ):
        return None
    return f"{model_id}@{version}:r{revision}"


__all__ = ["DynamicAssurancePanel"]
