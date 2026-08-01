"""Durable active/challenger effect-model registry over StateStore."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.core.assurance_twin.effect_model import (
    CausalEvidenceGrade,
    ChallengerUpdate,
    EffectModel,
    EffectModelStatus,
    update_challenger,
)
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.providers.state_store import StateStore

_PREFIX = "dynamic-effect-model"


@dataclass(frozen=True, slots=True)
class RegistryUpdate:
    accepted: bool
    reason: str
    model_ref: str | None = None


class StateStoreEffectModelRegistry:
    """Persist models while keeping active promotion outside this service."""

    def __init__(self, store: StateStore, *, max_retries: int = 3) -> None:
        if max_retries < 1:
            raise ValueError("effect model registry max_retries MUST be >= 1")
        self._store = store
        self._max_retries = max_retries

    async def register(self, model: EffectModel, *, registered_by: str) -> bool:
        """Register one explicit model version once; never replace it."""

        if not registered_by:
            raise ValueError("effect model registered_by MUST be non-empty")
        key = _state_key(model.status, model.action_type_id, model.metric)
        return await self._store.write_state_with_audit_if_absent(
            key,
            _serialize(model),
            {
                "actor": registered_by,
                "action_kind": "dynamic.effect_model.registered",
                "mode": "shadow",
                "model_ref": _model_ref(model),
                "model_status": model.status.value,
                "action_type_id": model.action_type_id,
                "metric": model.metric,
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            },
        )

    async def get(
        self,
        *,
        status: EffectModelStatus,
        action_type_id: str,
        metric: str,
    ) -> EffectModel | None:
        raw = await self._store.read_state(_state_key(status, action_type_id, metric))
        return _deserialize(raw) if raw is not None else None

    async def update_from_outcome(self, outcome: ResponseOutcome) -> RegistryUpdate:
        """Apply a scorable outcome to its challenger with optimistic concurrency."""

        if outcome.metric is None:
            return RegistryUpdate(False, "outcome_metric_unavailable")
        key = _state_key(
            EffectModelStatus.CHALLENGER,
            outcome.action_type_id,
            outcome.metric,
        )
        for _ in range(self._max_retries):
            raw = await self._store.read_state(key)
            if raw is None:
                return RegistryUpdate(False, "challenger_not_registered")
            current = _deserialize(raw)
            update: ChallengerUpdate = update_challenger(current, outcome)
            if not update.accepted:
                return RegistryUpdate(False, update.reason, _model_ref(current))
            changed = update.model
            accepted = await self._store.compare_and_set_state_with_audit(
                key,
                _serialize(changed),
                expected_revision=current.revision,
                audit_entry={
                    "actor": "Norns",
                    "producer_principal": "Norns",
                    "action_kind": "dynamic.effect_model.challenger.updated",
                    "mode": "shadow",
                    "response_outcome_id": str(outcome.outcome_id),
                    "model_ref": _model_ref(changed),
                    "action_type_id": changed.action_type_id,
                    "metric": changed.metric,
                    "sample_count": changed.sample_count,
                    "mean_absolute_error": changed.mean_absolute_error,
                    "recorded_at": outcome.recorded_at.isoformat(),
                },
            )
            if accepted:
                return RegistryUpdate(True, "challenger_updated", _model_ref(changed))
        return RegistryUpdate(False, "revision_conflict")


def _state_key(status: EffectModelStatus, action_type_id: str, metric: str) -> str:
    digest = hashlib.sha256(f"{action_type_id}\n{metric}".encode()).hexdigest()
    return f"{_PREFIX}:{status.value}:{digest}"


def _serialize(model: EffectModel) -> dict[str, object]:
    return {
        "model_id": model.model_id,
        "version": model.version,
        "revision": model.revision,
        "action_type_id": model.action_type_id,
        "metric": model.metric,
        "status": model.status.value,
        "evidence_grade": model.evidence_grade.value,
        "causal_evidence_receipt_digest": model.causal_evidence_receipt_digest,
        "learned_at": model.learned_at.isoformat(),
        "learned_through": model.learned_through.isoformat(),
        "sample_count": model.sample_count,
        "bias_correction": model.bias_correction,
        "mean_absolute_error": model.mean_absolute_error,
        "interval_radius": model.interval_radius,
    }


def _deserialize(raw: Mapping[str, Any]) -> EffectModel:
    return EffectModel(
        model_id=_required_text(raw, "model_id"),
        version=_required_text(raw, "version"),
        revision=int(raw["revision"]),
        action_type_id=_required_text(raw, "action_type_id"),
        metric=_required_text(raw, "metric"),
        status=EffectModelStatus(_required_text(raw, "status")),
        evidence_grade=CausalEvidenceGrade(_required_text(raw, "evidence_grade")),
        causal_evidence_receipt_digest=_required_text(raw, "causal_evidence_receipt_digest"),
        learned_at=_datetime(raw, "learned_at"),
        learned_through=_datetime(raw, "learned_through"),
        sample_count=int(raw.get("sample_count", 0)),
        bias_correction=float(raw.get("bias_correction", 0.0)),
        mean_absolute_error=float(raw.get("mean_absolute_error", 0.0)),
        interval_radius=float(raw.get("interval_radius", 0.0)),
    )


def _required_text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"stored effect model {key} MUST be non-empty")
    return value


def _datetime(raw: Mapping[str, Any], key: str) -> datetime:
    value = _required_text(raw, key)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"stored effect model {key} MUST be timezone-aware")
    return parsed


def _model_ref(model: EffectModel) -> str:
    return f"{model.model_id}@{model.version}:r{model.revision}"


__all__ = ["RegistryUpdate", "StateStoreEffectModelRegistry"]
