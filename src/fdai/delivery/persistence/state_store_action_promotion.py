"""StateStore-backed ActionPromotionRegistry with fail-closed refresh."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fdai.core.risk_gate import (
    ActionModeRecord,
    ActionPromotionRegistry,
    OperationalPromotionReceiptVerifier,
    PersistedPromotionAuthorityVerifier,
    PromotionMetrics,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.state_store import StateStore

_PREFIX = "action_promotion:"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class StateStoreActionPromotionRegistry(ActionPromotionRegistry):
    """Keep the RiskGate sync read API over an asynchronously refreshed cache."""

    def __init__(
        self,
        *,
        store: StateStore,
        receipt_verifier: OperationalPromotionReceiptVerifier | None = None,
        persisted_authority_verifier: PersistedPromotionAuthorityVerifier | None = None,
        allow_legacy_metrics: bool = False,
    ) -> None:
        super().__init__(
            receipt_verifier=receipt_verifier,
            allow_legacy_metrics=allow_legacy_metrics,
        )
        self._store = store
        self._persisted_authority_verifier = persisted_authority_verifier

    async def refresh(self, action_type: str) -> None:
        try:
            raw = await self._store.read_state(_key(action_type))
            if raw is None:
                self._records.pop(action_type, None)
                return
            record = _deserialize(raw)
            if record.action_type != action_type:
                raise ValueError("persisted action_type does not match key")
            if record.mode is Mode.ENFORCE:
                _validate_enforce_attribution(record)
                verifier = self._persisted_authority_verifier
                attribution = (
                    record.action_type_version,
                    record.action_type_digest,
                    record.promotion_evidence_digest,
                    record.fdai_revision,
                    record.scenario_set_version,
                )
                if verifier is None or any(value is None for value in attribution):
                    raise ValueError("persisted ENFORCE lacks verified O7 attribution")
                accepted = await verifier.verify(
                    action_type=record.action_type,
                    action_type_version=record.action_type_version or "",
                    action_type_digest=record.action_type_digest or "",
                    evidence_digest=record.promotion_evidence_digest or "",
                    fdai_revision=record.fdai_revision or "",
                    scenario_set_version=record.scenario_set_version or "",
                )
                if not accepted:
                    raise ValueError("persisted ENFORCE O7 attribution was rejected")
            self._records[action_type] = record
        except Exception:
            # A stale cached ENFORCE is unsafe when the authority store is
            # unavailable or corrupt. Clear it so mode_of() returns SHADOW.
            self._records.pop(action_type, None)

    async def persist(self, action_type: str) -> None:
        record = self.record(action_type)
        if record is None:
            record = self.demote(action_type)
        await self._store.write_state(_key(action_type), _serialize(record))


def _key(action_type: str) -> str:
    return f"{_PREFIX}{action_type}"


def _serialize(record: ActionModeRecord) -> dict[str, Any]:
    metrics = record.metrics
    return {
        "schema_version": "1.0.0",
        "action_type": record.action_type,
        "mode": record.mode.value,
        "promoted_at": record.promoted_at.isoformat() if record.promoted_at else None,
        "demoted_at": record.demoted_at.isoformat() if record.demoted_at else None,
        "promotion_evidence_digest": record.promotion_evidence_digest,
        "fdai_revision": record.fdai_revision,
        "scenario_set_version": record.scenario_set_version,
        "action_type_version": record.action_type_version,
        "action_type_digest": record.action_type_digest,
        "metrics": (
            {
                "action_type": metrics.action_type,
                "shadow_days": metrics.shadow_days,
                "samples": metrics.samples,
                "accuracy": metrics.accuracy,
                "policy_escapes": metrics.policy_escapes,
            }
            if metrics is not None
            else None
        ),
    }


def _deserialize(raw: Any) -> ActionModeRecord:
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0.0":
        raise ValueError("unsupported promotion state")
    metrics_raw = raw.get("metrics")
    metrics = None
    if isinstance(metrics_raw, dict):
        metrics = PromotionMetrics(
            action_type=str(metrics_raw["action_type"]),
            shadow_days=int(metrics_raw["shadow_days"]),
            samples=int(metrics_raw["samples"]),
            accuracy=float(metrics_raw["accuracy"]),
            policy_escapes=int(metrics_raw["policy_escapes"]),
        )
    return ActionModeRecord(
        action_type=str(raw["action_type"]),
        mode=Mode(str(raw["mode"])),
        promoted_at=_timestamp(raw.get("promoted_at")),
        demoted_at=_timestamp(raw.get("demoted_at")),
        metrics=metrics,
        promotion_evidence_digest=_optional_text(raw.get("promotion_evidence_digest")),
        fdai_revision=_optional_text(raw.get("fdai_revision")),
        scenario_set_version=_optional_text(raw.get("scenario_set_version")),
        action_type_version=_optional_text(raw.get("action_type_version")),
        action_type_digest=_optional_text(raw.get("action_type_digest")),
    )


def _timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("promotion timestamp MUST be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("promotion timestamp MUST be timezone-aware")
    return parsed


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("promotion evidence attribution MUST be non-empty text")
    return value


def _validate_enforce_attribution(record: ActionModeRecord) -> None:
    if record.promoted_at is None:
        raise ValueError("persisted ENFORCE requires a promotion timestamp")
    if record.metrics is not None and record.metrics.action_type != record.action_type:
        raise ValueError("persisted ENFORCE metrics do not match ActionType")
    if (
        record.promotion_evidence_digest is None
        or _DIGEST.fullmatch(record.promotion_evidence_digest) is None
        or record.action_type_digest is None
        or _DIGEST.fullmatch(record.action_type_digest) is None
        or record.fdai_revision is None
        or _REVISION.fullmatch(record.fdai_revision) is None
        or not record.action_type_version
        or not record.scenario_set_version
    ):
        raise ValueError("persisted ENFORCE attribution is malformed")


__all__ = ["StateStoreActionPromotionRegistry"]
