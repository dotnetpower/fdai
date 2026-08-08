"""Durable exact-key storage for measured operational-promotion receipts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from math import isfinite
from typing import Any

from fdai.core.measurement import OperationalPromotionReceipt
from fdai.shared.providers.state_store import StateStore

_PREFIX = "operational-promotion-receipt:"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_TEXT_FIELDS = (
    "fdai_revision",
    "scenario_set_version",
    "action_type_name",
    "action_type_version",
    "action_type_digest",
    "evidence_digest",
)
_INT_FIELDS = (
    "live_observation_days",
    "sample_count",
    "benchmark_samples",
    "live_shadow_samples",
    "correct_count",
    "policy_escapes",
    "executed_samples",
    "recurrence_complete_samples",
    "recurrence_incomplete_samples",
    "causal_evidence_failures",
)
_FLOAT_FIELDS = (
    "observation_days",
    "accuracy",
    "accuracy_ci_lower",
    "accuracy_ci_upper",
    "benchmark_accuracy",
    "benchmark_accuracy_ci_lower",
    "benchmark_accuracy_ci_upper",
    "live_shadow_accuracy",
    "live_shadow_accuracy_ci_lower",
    "live_shadow_accuracy_ci_upper",
    "rollback_rate",
    "recurrence_rate",
    "simulation_review_rate",
)
_EXPECTED_FIELDS = frozenset((*_TEXT_FIELDS, *_INT_FIELDS, *_FLOAT_FIELDS, "ready", "gaps"))


class StateStoreOperationalPromotionReceiptStore:
    """Persist immutable receipts without granting promotion authority."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def save(self, receipt: OperationalPromotionReceipt) -> None:
        key = _key(
            action_type_name=receipt.action_type_name,
            fdai_revision=receipt.fdai_revision,
            scenario_set_version=receipt.scenario_set_version,
            evidence_digest=receipt.evidence_digest,
        )
        value = {"schema_version": "1.0.0", "receipt": receipt.as_json()}
        created = await self._store.write_state_with_audit_if_absent(
            key,
            value,
            {
                "actor": "fdai.delivery.persistence.operational-promotion",
                "producer_principal": "Norns",
                "action_kind": "operational_promotion.receipt_stored",
                "mode": "shadow",
                "correlation_id": (
                    f"operational-promotion:{receipt.scenario_set_version}:"
                    f"{receipt.action_type_name}"
                ),
                "idempotency_key": key,
                "action_type_name": receipt.action_type_name,
                "fdai_revision": receipt.fdai_revision,
                "scenario_set_version": receipt.scenario_set_version,
                "evidence_digest": receipt.evidence_digest,
                "ready": receipt.ready,
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            },
        )
        if created:
            return
        existing = await self.load(
            action_type_name=receipt.action_type_name,
            fdai_revision=receipt.fdai_revision,
            scenario_set_version=receipt.scenario_set_version,
            evidence_digest=receipt.evidence_digest,
        )
        if existing != receipt:
            raise ValueError("operational promotion receipt key collision")

    async def load(
        self,
        *,
        action_type_name: str,
        fdai_revision: str,
        scenario_set_version: str,
        evidence_digest: str,
    ) -> OperationalPromotionReceipt | None:
        raw = await self._store.read_state(
            _key(
                action_type_name=action_type_name,
                fdai_revision=fdai_revision,
                scenario_set_version=scenario_set_version,
                evidence_digest=evidence_digest,
            )
        )
        if raw is None:
            return None
        if raw.get("schema_version") != "1.0.0":
            raise ValueError("unsupported operational promotion receipt state")
        receipt = raw.get("receipt")
        if not isinstance(receipt, Mapping):
            raise ValueError("operational promotion receipt state is malformed")
        return _decode_receipt(receipt)


def _key(
    *,
    action_type_name: str,
    fdai_revision: str,
    scenario_set_version: str,
    evidence_digest: str,
) -> str:
    if _SAFE_ID.fullmatch(action_type_name) is None:
        raise ValueError("action_type_name is invalid")
    if _REVISION.fullmatch(fdai_revision) is None:
        raise ValueError("fdai_revision is invalid")
    if _SAFE_ID.fullmatch(scenario_set_version) is None:
        raise ValueError("scenario_set_version is invalid")
    if _DIGEST.fullmatch(evidence_digest) is None:
        raise ValueError("evidence_digest is invalid")
    return f"{_PREFIX}{action_type_name}:{fdai_revision}:{scenario_set_version}:{evidence_digest}"


def _decode_receipt(raw: Mapping[str, Any]) -> OperationalPromotionReceipt:
    if frozenset(raw) != _EXPECTED_FIELDS:
        raise ValueError("operational promotion receipt fields do not match schema")
    values = dict(raw)
    for field in _TEXT_FIELDS:
        value = values[field]
        if not isinstance(value, str) or not value:
            raise ValueError(f"operational promotion receipt {field} is invalid")
    for field in _INT_FIELDS:
        value = values[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"operational promotion receipt {field} is invalid")
    for field in _FLOAT_FIELDS:
        value = values[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            raise ValueError(f"operational promotion receipt {field} is invalid")
        values[field] = float(value)
    if not isinstance(values["ready"], bool):
        raise ValueError("operational promotion receipt ready is invalid")
    gaps = values["gaps"]
    if not isinstance(gaps, list) or any(not isinstance(item, str) for item in gaps):
        raise ValueError("operational promotion receipt gaps are invalid")
    values["gaps"] = tuple(gaps)
    receipt = OperationalPromotionReceipt(**values)
    if _REVISION.fullmatch(receipt.fdai_revision) is None:
        raise ValueError("operational promotion receipt revision is invalid")
    if _DIGEST.fullmatch(receipt.action_type_digest) is None:
        raise ValueError("operational promotion receipt action digest is invalid")
    if _DIGEST.fullmatch(receipt.evidence_digest) is None:
        raise ValueError("operational promotion receipt evidence digest is invalid")
    return receipt


__all__ = ["StateStoreOperationalPromotionReceiptStore"]
