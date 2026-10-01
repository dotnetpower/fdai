"""Bounded non-mutating rollback rehearsal receipts for Vidar."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from fdai.agents._framework.topics import stable_idempotency_key

RehearsalOutcome = Literal["passed", "failed", "held"]
REHEARSAL_KIND = "rollback_rehearsal_receipt"
_MAX_REASON = 256


class RollbackRehearsalPort(Protocol):
    """Non-mutating dry-run seam for rollback contract rehearsal."""

    async def rehearse(self, command: Mapping[str, Any]) -> Mapping[str, Any]: ...


def unbound_receipt(*, action_type: str, contract: str, recorded_at: datetime) -> dict[str, Any]:
    return build_receipt(
        action_type=action_type,
        contract=contract,
        outcome="held",
        reason="rehearsal_port_unbound",
        recorded_at=recorded_at,
        rehearsal_version="1.0.0",
    )


def build_receipt(
    *,
    action_type: str,
    contract: str,
    outcome: RehearsalOutcome,
    reason: str,
    recorded_at: datetime,
    rehearsal_version: str,
) -> dict[str, Any]:
    recorded_at = _to_utc(recorded_at)
    bounded_reason = reason.strip()[:_MAX_REASON]
    payload = {
        "producer_principal": "Vidar",
        "kind": REHEARSAL_KIND,
        "correlation_id": f"rollback-rehearsal:{action_type}",
        "resource_id": f"action-type:{action_type}",
        "action_type": action_type,
        "rollback_contract": contract,
        "outcome": outcome,
        "reason": bounded_reason,
        "recorded_at": recorded_at.isoformat(),
        "rehearsal_version": rehearsal_version.strip()[:64] or "1.0.0",
    }
    payload["receipt_digest"] = digest(payload)
    payload["idempotency_key"] = stable_idempotency_key(
        REHEARSAL_KIND,
        action_type,
        contract,
        payload["recorded_at"],
        payload["receipt_digest"],
    )
    return payload


def command(*, action_type: str, contract: str) -> dict[str, str]:
    return {
        "mode": "dry_run",
        "action_type": action_type,
        "rollback_contract": contract,
    }


def digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        {key: value for key, value in payload.items() if key in _DIGEST_FIELDS},
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def durable_key(receipt: Mapping[str, Any]) -> str:
    action_type = str(receipt.get("action_type") or "")
    digest_scope = str(receipt.get("receipt_digest") or "").removeprefix("sha256:")
    action_digest = hashlib.sha256(action_type.encode("utf-8")).hexdigest()
    return f"pantheon/vidar/rehearsal/{action_digest}/{digest_scope}"


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("Vidar rehearsal clock MUST return a timezone-aware datetime")
    return value.astimezone(UTC)


_DIGEST_FIELDS = frozenset(
    {
        "kind",
        "action_type",
        "rollback_contract",
        "outcome",
        "reason",
        "recorded_at",
        "rehearsal_version",
    }
)
