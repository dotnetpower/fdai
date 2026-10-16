"""Durable active/challenger effect-model registry over StateStore."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
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
_MAX_FEEDBACK_RECEIPTS = 256
_UPDATE_TIMEOUT_SECONDS = 5.0
_RECEIPT_FIELDS = frozenset({"outcome", "idempotency", "action", "prediction", "content"})


@dataclass(frozen=True, slots=True)
class RegistryUpdate:
    accepted: bool
    reason: str
    model_ref: str | None = None


class StateStoreEffectModelRegistry:
    """Persist models while keeping active promotion outside this service."""

    def __init__(
        self,
        store: StateStore,
        *,
        max_retries: int = 3,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_retries < 1:
            raise ValueError("effect model registry max_retries MUST be >= 1")
        self._store = store
        self._max_retries = max_retries
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def register(self, model: EffectModel, *, registered_by: str) -> bool:
        """Register one explicit model version once; never replace it."""

        if not registered_by:
            raise ValueError("effect model registered_by MUST be non-empty")
        key = _state_key(model.status, model.action_type_id, model.metric)
        value = _serialize(model)
        if model.status is EffectModelStatus.CHALLENGER:
            value["feedback_checkpoint"] = _checkpoint(model.learned_through, {}, None)
        return await self._store.write_state_with_audit_if_absent(
            key,
            value,
            {
                "actor": registered_by,
                "action_kind": "dynamic.effect_model.registered",
                "mode": "shadow",
                "model_ref": _model_ref(model),
                "model_status": model.status.value,
                "action_type_id": model.action_type_id,
                "metric": model.metric,
                "recorded_at": self._clock().isoformat(),
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
        if raw is None:
            return None
        model = _deserialize(raw)
        if status is EffectModelStatus.CHALLENGER:
            checkpoint = _read_checkpoint(raw, model)
            if checkpoint is None or checkpoint[2] is not None:
                return None
        return model

    async def update_from_outcome(self, outcome: ResponseOutcome) -> RegistryUpdate:
        """Commit a challenger, its event receipt, and audit together under one deadline."""
        async with asyncio.timeout(_UPDATE_TIMEOUT_SECONDS):
            return await self._update_from_outcome(outcome)

    async def _update_from_outcome(self, outcome: ResponseOutcome) -> RegistryUpdate:

        if outcome.metric is None:
            return RegistryUpdate(False, "outcome_metric_unavailable")
        key = _state_key(
            EffectModelStatus.CHALLENGER,
            outcome.action_type_id,
            outcome.metric,
        )
        event_key = _digest(str(outcome.event_id))
        receipt = {
            "outcome": _digest(str(outcome.outcome_id)),
            "idempotency": _digest(outcome.idempotency_key),
            "action": _digest(str(outcome.action_id)),
            "prediction": _digest(outcome.prediction_id),
            "content": _digest(outcome.model_dump(mode="json")),
        }
        for _ in range(self._max_retries):
            raw = await self._store.read_state(key)
            if raw is None:
                return RegistryUpdate(False, "challenger_not_registered")
            current = _deserialize(raw)
            checkpoint = _read_checkpoint(raw, current)
            if checkpoint is None:
                return RegistryUpdate(False, "untracked_challenger_requires_rebuild")
            cutoff, receipts, hold = checkpoint
            if hold is not None:
                return RegistryUpdate(False, hold, _model_ref(current))
            conflict = False
            for previous in receipts.values():
                if previous == receipt:
                    return RegistryUpdate(False, "outcome_already_applied", _model_ref(current))
                if (
                    previous["outcome"] == receipt["outcome"]
                    or previous["idempotency"] == receipt["idempotency"]
                    or (
                        previous["action"] == receipt["action"]
                        and previous["prediction"] == receipt["prediction"]
                    )
                ):
                    conflict = True
            if conflict:
                hold = "outcome_revision_requires_rebuild"
            elif event_key in receipts:
                return RegistryUpdate(False, "dependent_event_already_learned", _model_ref(current))
            now = self._clock()
            if now.tzinfo is None:
                raise ValueError("effect learning clock MUST be timezone-aware")
            if outcome.recorded_at > now:
                return RegistryUpdate(False, "outcome_recorded_in_future", _model_ref(current))
            update: ChallengerUpdate = update_challenger(current, outcome, learning_cutoff=cutoff)
            if hold is None and not update.accepted:
                return RegistryUpdate(False, update.reason, _model_ref(current))
            if hold is None and len(receipts) >= _MAX_FEEDBACK_RECEIPTS:
                hold = "feedback_checkpoint_full"
            if hold is None:
                receipts[event_key] = receipt
            changed = replace(
                current if hold is not None else update.model,
                revision=current.revision + 1,
                learned_through=max(current.learned_through, outcome.recorded_at, now),
            )
            value = _serialize(changed)
            value["feedback_checkpoint"] = _checkpoint(cutoff, receipts, hold)
            accepted = await self._store.compare_and_set_state_with_audit(
                key,
                value,
                expected_revision=current.revision,
                audit_entry={
                    "actor": "Norns",
                    "producer_principal": "Norns",
                    "action_kind": (
                        "dynamic.effect_model.challenger.held"
                        if hold is not None
                        else "dynamic.effect_model.challenger.updated"
                    ),
                    "mode": "shadow",
                    "response_outcome_id": str(outcome.outcome_id),
                    "event_id": str(outcome.event_id),
                    "action_id": str(outcome.action_id),
                    "prediction_id": outcome.prediction_id,
                    "outcome_digest": receipt["content"],
                    "reason": hold or "challenger_updated",
                    "execution_authority": False,
                    "promotion_authority": False,
                    "model_ref": _model_ref(changed),
                    "action_type_id": changed.action_type_id,
                    "metric": changed.metric,
                    "sample_count": changed.sample_count,
                    "mean_absolute_error": changed.mean_absolute_error,
                    "outcome_recorded_at": outcome.recorded_at.isoformat(),
                    "recorded_at": now.isoformat(),
                },
            )
            if accepted:
                return RegistryUpdate(
                    hold is None, hold or "challenger_updated", _model_ref(changed)
                )
        return RegistryUpdate(False, "revision_conflict")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _checkpoint(
    cutoff: datetime, receipts: dict[str, dict[str, str]], hold: str | None
) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "cutoff": cutoff.isoformat(),
        "receipts": receipts,
        "hold_reason": hold,
    }


def _read_checkpoint(
    raw: Mapping[str, Any], model: EffectModel
) -> tuple[datetime, dict[str, dict[str, str]], str | None] | None:
    value = raw.get("feedback_checkpoint")
    if value is None:
        return (model.learned_through, {}, None) if model.sample_count == 0 else None
    if (
        not isinstance(value, Mapping)
        or set(value) != {"schema_version", "cutoff", "receipts", "hold_reason"}
        or value["schema_version"] != "1.0.0"
        or not isinstance(value["receipts"], Mapping)
        or len(value["receipts"]) > _MAX_FEEDBACK_RECEIPTS
        or (value["hold_reason"] is not None and not isinstance(value["hold_reason"], str))
        or value["hold_reason"]
        not in {None, "outcome_revision_requires_rebuild", "feedback_checkpoint_full"}
    ):
        raise ValueError("stored effect feedback checkpoint is invalid; reviewed rebuild required")
    cutoff = _datetime(value, "cutoff")
    if not model.learned_at <= cutoff <= model.learned_through:
        raise ValueError("stored effect feedback cutoff is outside the model knowledge window")
    receipts: dict[str, dict[str, str]] = {}
    for event, receipt in value["receipts"].items():
        if (
            not _is_digest(event)
            or not isinstance(receipt, Mapping)
            or set(receipt) != _RECEIPT_FIELDS
            or any(not _is_digest(item) for item in receipt.values())
        ):
            raise ValueError("stored effect feedback receipt is invalid; reviewed rebuild required")
        receipts[event] = dict(receipt)
    return cutoff, receipts, value["hold_reason"]


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


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
