"""Durable active and challenger graph effect model registry."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.core.assurance_twin.effect_model import CausalEvidenceGrade, EffectModelStatus
from fdai.core.assurance_twin.graph_effect import GraphEffectModel
from fdai.core.assurance_twin.graph_learning import (
    GraphModelLearningObservation,
    update_graph_challenger,
)
from fdai.shared.providers.state_store import StateStore

_PREFIX = "dynamic-graph-effect-model"


@dataclass(frozen=True, slots=True)
class GraphRegistryUpdate:
    accepted: bool
    reason: str
    model_ref: str | None = None


class StateStoreGraphEffectModelRegistry:
    def __init__(self, store: StateStore, *, max_models: int = 1000, max_retries: int = 3) -> None:
        if not 1 <= max_models <= 1000 or max_retries < 1:
            raise ValueError("graph registry limits MUST be positive and bounded")
        self._store = store
        self._max_models = max_models
        self._max_retries = max_retries

    async def register(self, model: GraphEffectModel, *, registered_by: str) -> bool:
        if not registered_by:
            raise ValueError("graph model registered_by MUST be non-empty")
        return await self._store.write_state_with_audit_if_absent(
            _state_key(model),
            _serialize(model),
            {
                "actor": registered_by,
                "action_kind": "dynamic.graph_effect_model.registered",
                "mode": "shadow",
                "model_ref": model.ref,
                "model_status": model.status.value,
                "trigger_ref": model.trigger_ref,
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            },
        )

    async def list_models(
        self,
        *,
        status: EffectModelStatus,
        trigger_refs: tuple[str, ...],
    ) -> tuple[GraphEffectModel, ...]:
        rows = await self._store.read_states(f"{_PREFIX}:{status.value}:", limit=self._max_models)
        if len(rows) >= self._max_models:
            raise ValueError("graph effect model registry partition is truncated")
        models = tuple(
            sorted(
                (model for row in rows if (model := _deserialize(row)).trigger_ref in trigger_refs),
                key=lambda item: (item.trigger_ref, item.model_id, item.version, item.revision),
            )
        )
        return models

    async def update_from_observation(
        self,
        observation: GraphModelLearningObservation,
    ) -> GraphRegistryUpdate:
        rows = await self._store.read_states(
            f"{_PREFIX}:{EffectModelStatus.CHALLENGER.value}:",
            limit=self._max_models,
        )
        if len(rows) >= self._max_models:
            return GraphRegistryUpdate(False, "challenger_registry_truncated")
        models = tuple(_deserialize(row) for row in rows)
        if any(observation.digest in model.applied_observation_digests for model in models):
            return GraphRegistryUpdate(False, "observation_already_applied")
        observation_lineage = observation.model_ref.rsplit(":r", maxsplit=1)[0]
        matches = tuple(
            model for model in models if f"{model.model_id}@{model.version}" == observation_lineage
        )
        if len(matches) != 1:
            return GraphRegistryUpdate(False, "challenger_not_found_or_ambiguous")
        current = matches[0]
        for _ in range(self._max_retries):
            update = update_graph_challenger(current, observation)
            if not update.accepted:
                return GraphRegistryUpdate(False, update.reason, current.ref)
            changed = update.model
            accepted = await self._store.compare_and_set_state_with_audit(
                _state_key(current),
                _serialize(changed),
                expected_revision=current.revision,
                audit_entry={
                    "actor": "Norns",
                    "producer_principal": "Norns",
                    "action_kind": "dynamic.graph_effect_model.challenger.updated",
                    "mode": "shadow",
                    "model_ref": changed.ref,
                    "prediction_digest": observation.prediction_digest,
                    "observation_digest": observation.observation_digest,
                    "recorded_at": observation.recorded_at.isoformat(),
                },
            )
            if accepted:
                return GraphRegistryUpdate(True, "challenger_updated", changed.ref)
            stored = await self._store.read_state(_state_key(current))
            if stored is None:
                return GraphRegistryUpdate(False, "challenger_disappeared")
            current = _deserialize(stored)
        return GraphRegistryUpdate(False, "revision_conflict")


def _state_key(model: GraphEffectModel) -> str:
    identity = "\0".join(
        (
            model.trigger_ref,
            model.source_type,
            *model.link_path,
            model.target_type,
            model.target_metric,
        )
    )
    return f"{_PREFIX}:{model.status.value}:{hashlib.sha256(identity.encode()).hexdigest()}"


def _serialize(model: GraphEffectModel) -> dict[str, object]:
    return {
        "model_id": model.model_id,
        "version": model.version,
        "revision": model.revision,
        "status": model.status.value,
        "trigger_ref": model.trigger_ref,
        "source_type": model.source_type,
        "link_path": list(model.link_path),
        "target_type": model.target_type,
        "target_metric": model.target_metric,
        "propagation_lag_seconds": model.propagation_lag_seconds,
        "gain": model.gain,
        "offset": model.offset,
        "interval_radius": model.interval_radius,
        "evidence_grade": model.evidence_grade.value,
        "causal_evidence_receipt_digest": model.causal_evidence_receipt_digest,
        "learned_through": model.learned_through.isoformat(),
        "sample_count": model.sample_count,
        "mean_absolute_error": model.mean_absolute_error,
        "applied_observation_digests": list(model.applied_observation_digests),
    }


def _deserialize(raw: Mapping[str, Any]) -> GraphEffectModel:
    link_path = raw.get("link_path")
    if not isinstance(link_path, list) or any(not isinstance(item, str) for item in link_path):
        raise ValueError("stored graph effect link_path MUST be a string list")
    applied = raw.get("applied_observation_digests", [])
    if not isinstance(applied, list) or any(not isinstance(item, str) for item in applied):
        raise ValueError("stored graph effect observation digests MUST be a string list")
    return GraphEffectModel(
        model_id=_text(raw, "model_id"),
        version=_text(raw, "version"),
        revision=int(raw["revision"]),
        status=EffectModelStatus(_text(raw, "status")),
        trigger_ref=_text(raw, "trigger_ref"),
        source_type=_text(raw, "source_type"),
        link_path=tuple(link_path),
        target_type=_text(raw, "target_type"),
        target_metric=_text(raw, "target_metric"),
        propagation_lag_seconds=int(raw["propagation_lag_seconds"]),
        gain=float(raw["gain"]),
        offset=float(raw["offset"]),
        interval_radius=float(raw["interval_radius"]),
        evidence_grade=CausalEvidenceGrade(_text(raw, "evidence_grade")),
        causal_evidence_receipt_digest=_text(raw, "causal_evidence_receipt_digest"),
        learned_through=_timestamp(raw, "learned_through"),
        sample_count=int(raw.get("sample_count", 0)),
        mean_absolute_error=float(raw.get("mean_absolute_error", 0.0)),
        applied_observation_digests=tuple(applied),
    )


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"stored graph effect {key} MUST be non-empty")
    return value


def _timestamp(raw: Mapping[str, Any], key: str) -> datetime:
    parsed = datetime.fromisoformat(_text(raw, key).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"stored graph effect {key} MUST be timezone-aware")
    return parsed


__all__ = ["GraphRegistryUpdate", "StateStoreGraphEffectModelRegistry"]
