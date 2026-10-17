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
from fdai.core.assurance_twin.feedback_generation import (
    FeedbackRevisionSource,
    generation_evidence,
    read_admission,
    read_generation,
    rebuild_admission_valid,
)
from fdai.core.assurance_twin.feedback_rebuild import FeedbackRebuildCandidate, rebuild_feedback
from fdai.core.assurance_twin.prediction_evidence import prediction_available
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
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
        feedback_source: FeedbackRevisionSource | None = None,
    ) -> None:
        if max_retries < 1:
            raise ValueError("effect model registry max_retries MUST be >= 1")
        self._store = store
        self._max_retries = max_retries
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._feedback_source = feedback_source

    async def register(self, model: EffectModel, *, registered_by: str) -> bool:
        """Register one explicit model version once; never replace it."""

        if not registered_by:
            raise ValueError("effect model registered_by MUST be non-empty")
        key = _state_key(model.status, model.action_type_id, model.metric)
        value = _serialize(model)
        if model.status is EffectModelStatus.CHALLENGER:
            value["feedback_checkpoint"] = _checkpoint(model.learned_through, {}, None)
            value["registered_seed"] = _serialize(model)
            value["registered_seed_digest"] = _digest(_serialize(model))
            value["feedback_order"] = []
        value["state_digest"] = _storage_digest(value)
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

    async def inspect_registration(
        self,
        *,
        status: EffectModelStatus,
        action_type_id: str,
        metric: str,
    ) -> tuple[EffectModel, EffectModel | None] | None:
        """Inspect persisted lineage for configuration, not operational prediction."""
        raw = await self._store.read_state(_state_key(status, action_type_id, metric))
        if raw is None:
            return None
        model = _deserialize(raw)
        seed_raw = raw.get("registered_seed")
        if seed_raw is None:
            return model, None
        if not isinstance(seed_raw, Mapping):
            raise ValueError("stored effect model seed registration is invalid")
        seed = _deserialize(seed_raw)
        if raw.get("registered_seed_digest") != _digest(_serialize(seed)):
            raise ValueError("stored effect model seed registration digest is invalid")
        return model, seed

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
            if not await self._generation_current(raw, model):
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
        event_key = (
            outcome.prediction_snapshot.independence_key
            if outcome.prediction_snapshot is not None
            else _digest(str(outcome.event_id))
        )
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
            generation = read_generation(raw)
            if generation is not None:
                if not await self._generation_current(raw, current):
                    return RegistryUpdate(False, "model_generation_sources_unavailable")
                if str(outcome.outcome_id) in generation["covered_outcome_ids"]:
                    if outcome.revision_digest in generation["source_digests"]:
                        return RegistryUpdate(False, "outcome_already_applied", _model_ref(current))
                    return RegistryUpdate(False, "outcome_revision_requires_rebuild")
                if (
                    outcome.prediction_snapshot is not None
                    and outcome.prediction_snapshot.independence_key
                    in generation["covered_independence_keys"]
                ):
                    return RegistryUpdate(False, "dependent_event_already_learned")
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
            if hold is None:
                snapshot = outcome.prediction_snapshot
                if (
                    snapshot is None
                    or outcome.observed_at is None
                    or not await prediction_available(
                        self._store, snapshot, observed_at=outcome.observed_at
                    )
                ):
                    return RegistryUpdate(
                        False, "outcome_prediction_evidence_unavailable", _model_ref(current)
                    )
                generation_refs = generation["source_digests"] if generation is not None else ()
                revisions = tuple(
                    sorted(
                        set(
                            (
                                *generation_refs,
                                *(item["content"] for item in receipts.values()),
                                outcome.revision_digest,
                            )
                        )
                    )
                )
                if self._feedback_source is None or not await self._feedback_source.current(
                    revisions
                ):
                    return RegistryUpdate(False, "model_generation_sources_unavailable")
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
            for field in ("registered_seed", "registered_seed_digest"):
                if field in raw:
                    value[field] = raw[field]
            prior_order = raw.get("feedback_order", [])
            if (
                not isinstance(prior_order, list)
                or len(prior_order) > _MAX_FEEDBACK_RECEIPTS
                or any(not isinstance(item, str) for item in prior_order)
            ):
                raise ValueError("stored scalar feedback order is invalid")
            value["feedback_order"] = [
                *prior_order,
                *([str(outcome.outcome_id)] if hold is None else []),
            ]
            if generation is not None:
                value["generation_evidence"] = dict(generation)
            value["feedback_checkpoint"] = _checkpoint(cutoff, receipts, hold)
            value["state_digest"] = _storage_digest(value)
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

    async def _generation_current(self, raw: Mapping[str, Any], model: EffectModel) -> bool:
        generation = read_generation(raw)
        checkpoint = _read_checkpoint(raw, model)
        if checkpoint is None:
            return False
        additional = tuple(item["content"] for item in checkpoint[1].values())
        initial = generation["source_digests"] if generation is not None else ()
        revisions = tuple(sorted(set((*initial, *additional))))
        if not revisions:
            return generation is None
        if self._feedback_source is None:
            return False
        async with asyncio.timeout(_UPDATE_TIMEOUT_SECONDS):
            current = await self._feedback_source.current(revisions)
        if generation is None:
            return current
        admission = read_admission(generation["admission"])
        return current and rebuild_admission_valid(
            admission,
            manifest=generation["input_manifest_digest"],
            action_type=model.action_type_id,
            metric=model.metric,
            evaluated_at=self._clock(),
        )

    async def preview_rebuild(
        self,
        *,
        seed: EffectModel,
        outcomes: tuple[ResponseOutcome, ...],
        as_of: datetime,
    ) -> FeedbackRebuildCandidate | None:
        """Freeze the retained seed/order subject that a reviewed rebuild verifies."""
        raw = await self._store.read_state(
            _state_key(EffectModelStatus.CHALLENGER, seed.action_type_id, seed.metric)
        )
        if raw is None:
            return None
        _deserialize(raw)
        return _rebuild_candidate(raw, seed=seed, outcomes=outcomes, as_of=as_of)

    async def rebuild_challenger(
        self,
        *,
        seed: EffectModel,
        outcomes: tuple[ResponseOutcome, ...],
        as_of: datetime,
        expected_revision: int,
        admission: DecisionEvidenceAdmission | None,
    ) -> RegistryUpdate:
        """Replace only a reviewed challenger; retain the old generation atomically."""
        if admission is None or self._feedback_source is None:
            return RegistryUpdate(False, "rebuild_evidence_unavailable")
        if as_of.tzinfo is None or not seed.learned_through <= as_of <= self._clock():
            raise ValueError("feedback rebuild cutoff MUST be within known source time")
        async with asyncio.timeout(_UPDATE_TIMEOUT_SECONDS):
            key = _state_key(EffectModelStatus.CHALLENGER, seed.action_type_id, seed.metric)
            initial_raw = await self._store.read_state(key)
            if initial_raw is None:
                return RegistryUpdate(False, "challenger_not_registered")
            candidate = _rebuild_candidate(
                initial_raw,
                seed=seed,
                outcomes=outcomes,
                as_of=as_of,
            )
            if candidate is None:
                return RegistryUpdate(False, "rebuild_seed_mismatch")
            if candidate.accepted_episodes == 0:
                return RegistryUpdate(False, "rebuild_no_eligible_episodes")
            if not rebuild_admission_valid(
                admission,
                manifest=candidate.input_manifest_digest,
                action_type=seed.action_type_id,
                metric=seed.metric,
                evaluated_at=self._clock(),
            ):
                return RegistryUpdate(False, "rebuild_evidence_invalid")
            if not await self._feedback_source.current(candidate.source_digests):
                return RegistryUpdate(False, "rebuild_source_changed")
            for outcome in outcomes:
                if outcome.recorded_at > as_of:
                    continue
                snapshot = outcome.prediction_snapshot
                if snapshot is None or outcome.observed_at is None:
                    if not outcome.scorable:
                        continue
                    return RegistryUpdate(False, "rebuild_prediction_unavailable")
                if not await prediction_available(
                    self._store, snapshot, observed_at=outcome.observed_at
                ):
                    return RegistryUpdate(False, "rebuild_prediction_unavailable")
            raw = await self._store.read_state(key)
            existing_generation = read_generation(raw) if raw is not None else None
            if (
                raw is not None
                and existing_generation is not None
                and existing_generation["input_manifest_digest"] == candidate.input_manifest_digest
            ):
                return RegistryUpdate(
                    False, "rebuild_already_applied", _model_ref(_deserialize(raw))
                )
            if raw is None or raw.get("revision") != expected_revision:
                return RegistryUpdate(False, "revision_conflict")
            prior = _deserialize(raw)
            if (
                prior.model_id != seed.model_id
                or prior.version != seed.version
                or prior.learned_at != seed.learned_at
            ):
                return RegistryUpdate(False, "rebuild_seed_mismatch")
            changed = replace(
                candidate.model,
                revision=expected_revision + 1,
                learned_through=max(
                    prior.learned_through, candidate.model.learned_through, as_of, self._clock()
                ),
            )
            value = _serialize(changed)
            value["registered_seed"] = _serialize(seed)
            value["registered_seed_digest"] = _digest(_serialize(seed))
            value["feedback_order"] = []
            value["feedback_checkpoint"] = _checkpoint(as_of, {}, None)
            value["generation_evidence"] = generation_evidence(candidate, outcomes, admission)
            value["state_digest"] = _storage_digest(value)
            if not rebuild_admission_valid(
                admission,
                manifest=candidate.input_manifest_digest,
                action_type=seed.action_type_id,
                metric=seed.metric,
                evaluated_at=self._clock(),
            ):
                return RegistryUpdate(False, "rebuild_evidence_expired")
            stored = await self._store.compare_and_set_state_with_audit_and_insert(
                key,
                value,
                expected_revision=expected_revision,
                insert_key=f"{key}:generation:{expected_revision}:{_digest(raw)}",
                insert_value=dict(raw),
                audit_entry={
                    "actor": "Norns",
                    "producer_principal": "Norns",
                    "action_kind": "dynamic.effect_model.challenger.rebuilt",
                    "model_ref": _model_ref(changed),
                    "input_manifest_digest": candidate.input_manifest_digest,
                    "admission_receipt_digest": admission.receipt_digest,
                    "mode": "shadow",
                    "execution_authority": False,
                    "promotion_authority": False,
                    "recorded_at": self._clock().isoformat(),
                },
            )
            return RegistryUpdate(stored, "challenger_rebuilt" if stored else "revision_conflict")


def _rebuild_candidate(
    raw: Mapping[str, Any],
    *,
    seed: EffectModel,
    outcomes: tuple[ResponseOutcome, ...],
    as_of: datetime,
) -> FeedbackRebuildCandidate | None:
    if raw.get("registered_seed_digest") != _digest(_serialize(seed)) or raw.get(
        "registered_seed"
    ) != _serialize(seed):
        return None
    generation = read_generation(raw)
    earlier = generation["replay_order"] if generation is not None else []
    delta = raw.get("feedback_order", [])
    if (
        not isinstance(delta, list)
        or len(delta) > _MAX_FEEDBACK_RECEIPTS
        or any(not isinstance(item, str) for item in delta)
    ):
        raise ValueError("stored scalar feedback order is invalid")
    return rebuild_feedback(
        seed=seed,
        outcomes=outcomes,
        as_of=as_of,
        complete=True,
        replay_order=tuple(dict.fromkeys((*earlier, *delta))),
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _storage_digest(raw: Mapping[str, Any]) -> str:
    """Hash typed float parameters consistently across JSONB numeric rendering."""
    value = {key: item for key, item in raw.items() if key != "state_digest"}
    for field in ("bias_correction", "mean_absolute_error", "interval_radius"):
        if field in value:
            number = value[field]
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                raise ValueError("stored effect model numeric representation is invalid")
            try:
                normalized = float(number)
            except OverflowError as exc:
                raise ValueError(
                    "stored effect model numeric value is outside float range"
                ) from exc
            value[field] = 0.0 if normalized == 0.0 else normalized
    if "registered_seed" in value:
        seed = value["registered_seed"]
        if not isinstance(seed, Mapping):
            raise ValueError("stored effect model seed representation is invalid")
        normalized_seed = dict(seed)
        for field in ("bias_correction", "mean_absolute_error", "interval_radius"):
            number = normalized_seed[field]
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                raise ValueError("stored effect model seed numeric representation is invalid")
            normalized_seed[field] = 0.0 if number == 0.0 else float(number)
        value["registered_seed"] = normalized_seed
    return _digest(value)


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
        "bias_correction": 0.0 if model.bias_correction == 0.0 else float(model.bias_correction),
        "mean_absolute_error": (
            0.0 if model.mean_absolute_error == 0.0 else float(model.mean_absolute_error)
        ),
        "interval_radius": 0.0 if model.interval_radius == 0.0 else float(model.interval_radius),
        "prediction_model_ref": model.prediction_model_ref,
        "prediction_model_digest": model.prediction_model_digest,
        "unit": model.unit,
    }


def _deserialize(raw: Mapping[str, Any]) -> EffectModel:
    state_digest = raw.get("state_digest")
    if state_digest is not None and state_digest != _storage_digest(raw):
        raise ValueError("stored effect model state digest is invalid; reviewed recovery required")
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
        prediction_model_ref=_optional_text(raw, "prediction_model_ref"),
        prediction_model_digest=_optional_text(raw, "prediction_model_digest"),
        unit=_optional_text(raw, "unit"),
    )


def _required_text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"stored effect model {key} MUST be non-empty")
    return value


def _optional_text(raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError(f"stored effect model {key} MUST be non-empty when supplied")
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
