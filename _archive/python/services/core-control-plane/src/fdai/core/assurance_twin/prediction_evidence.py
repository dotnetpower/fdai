"""Prediction-time StateStore projection over the existing append-only audit."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from fdai.shared.contracts.models import EffectPredictionSnapshot
from fdai.shared.providers.state_store import StateStore

_PREFIX = "dynamic-effect-prediction:"


def _identity_key(snapshot: EffectPredictionSnapshot) -> str:
    identity = f"{snapshot.action_id}\n{snapshot.prediction_id}"
    return _PREFIX + "identity:" + hashlib.sha256(identity.encode()).hexdigest()


async def retain_prediction(
    store: StateStore, snapshot: EffectPredictionSnapshot, *, recorded_at: datetime
) -> None:
    if (
        recorded_at.tzinfo is None
        or recorded_at.utcoffset() is None
        or snapshot.predicted_at.tzinfo is None
        or snapshot.predicted_at.utcoffset() is None
        or recorded_at < snapshot.predicted_at
    ):
        raise ValueError("prediction retention time MUST follow prediction creation")
    value: dict[str, Any] = {
        "schema_version": "1.0.0",
        "snapshot": snapshot.model_dump(mode="json"),
        "snapshot_digest": snapshot.digest,
        "recorded_at": recorded_at.isoformat(),
        "execution_authority": False,
        "promotion_authority": False,
    }
    key = _PREFIX + snapshot.digest
    created = await store.write_state_pair_with_audit_if_absent(
        _identity_key(snapshot),
        {"snapshot_digest": snapshot.digest},
        insert_key=key,
        insert_value=value,
        audit_entry={
            "actor": "Forseti",
            "producer_principal": "Forseti",
            "action_kind": "dynamic.effect_prediction.frozen",
            "event_id": str(snapshot.event_id),
            "action_id": str(snapshot.action_id),
            "prediction_id": snapshot.prediction_id,
            "snapshot_digest": snapshot.digest,
            "mode": "shadow",
            "recorded_at": recorded_at.isoformat(),
            "execution_authority": False,
        },
    )
    if not created:
        identity = await store.read_state(_identity_key(snapshot))
        stored = await store.read_state(key)
        if (
            identity != {"snapshot_digest": snapshot.digest}
            or stored is None
            or stored.get("snapshot") != value["snapshot"]
        ):
            raise ValueError("retained prediction conflicts with its content identity")


async def prediction_available(
    store: StateStore, snapshot: EffectPredictionSnapshot, *, observed_at: datetime
) -> bool:
    identity = await store.read_state(_identity_key(snapshot))
    if identity != {"snapshot_digest": snapshot.digest}:
        return False
    raw = await store.read_state(_PREFIX + snapshot.digest)
    if raw is None:
        return False
    if (
        set(raw)
        != {
            "schema_version",
            "snapshot",
            "snapshot_digest",
            "recorded_at",
            "execution_authority",
            "promotion_authority",
        }
        or raw["schema_version"] != "1.0.0"
        or raw["snapshot_digest"] != snapshot.digest
        or raw["snapshot"] != snapshot.model_dump(mode="json")
        or raw["execution_authority"] is not False
        or raw["promotion_authority"] is not False
    ):
        raise ValueError("stored prediction evidence is invalid")
    recorded = raw["recorded_at"]
    if not isinstance(recorded, str):
        raise ValueError("stored prediction evidence time is invalid")
    recorded_at = datetime.fromisoformat(recorded)
    if recorded_at.tzinfo is None:
        raise ValueError("stored prediction evidence time MUST be timezone-aware")
    return snapshot.predicted_at <= recorded_at <= observed_at
