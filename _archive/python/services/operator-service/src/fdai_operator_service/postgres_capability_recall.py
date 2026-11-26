"""Bounded capability-recall projection for Operator promotion state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from fdai_operator_service.postgres_family_models import PostgresFamilyStoreUnavailableError


def merge_capability_recall_rows(
    modes: dict[str, object],
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    """Merge validated recall records into current ActionType modes."""

    for row in rows:
        raw = row.get("value")
        if not isinstance(raw, dict):
            raise PostgresFamilyStoreUnavailableError("capability_recall is not a JSON object")
        value = {str(key): item for key, item in raw.items()}
        action_type = value.get("action_type")
        reason = value.get("reason")
        recalled_at = value.get("recalled_at")
        lifted_at = value.get("lifted_at")
        if (
            value.get("schema_version") != "1.0.0"
            or not isinstance(action_type, str)
            or not action_type
            or len(action_type) > 256
            or not isinstance(reason, str)
            or not reason
            or len(reason) > 512
            or not isinstance(recalled_at, str)
            or not recalled_at
            or (lifted_at is not None and not isinstance(lifted_at, str))
        ):
            raise PostgresFamilyStoreUnavailableError(
                "authoritative capability recall state is malformed"
            )
        try:
            recall_times = [datetime.fromisoformat(recalled_at.replace("Z", "+00:00"))]
            if lifted_at is not None:
                recall_times.append(datetime.fromisoformat(lifted_at.replace("Z", "+00:00")))
        except ValueError as exc:
            raise PostgresFamilyStoreUnavailableError(
                "authoritative capability recall state is malformed"
            ) from exc
        if any(item.tzinfo is None for item in recall_times):
            raise PostgresFamilyStoreUnavailableError(
                "authoritative capability recall state is malformed"
            )
        recall = {
            "action_type": action_type,
            "active": lifted_at is None,
            "reason": reason,
            "recalled_at": recalled_at,
            "lifted_at": lifted_at,
        }
        stored_mode_record = modes.get(action_type)
        if stored_mode_record is None:
            mode_record: dict[str, object] = {
                "mode": "shadow",
                "promotion_kind": "gate_evidence",
                "capability_recall": None,
                "gate_status": None,
                "gate_status_source": "operator_attested",
                "gate_evidence_digest": None,
                "approval_receipt_digest": None,
                "operator_principal": None,
                "override_reason": None,
                "override_recorded_at": None,
                "safeguard_proof_source": "operator_attested",
            }
        elif isinstance(stored_mode_record, Mapping):
            mode_record = dict(stored_mode_record)
        else:
            raise PostgresFamilyStoreUnavailableError(
                "authoritative ActionType promotion state is malformed"
            )
        if recall["active"]:
            mode_record["mode"] = "shadow"
        mode_record["capability_recall"] = recall
        modes[action_type] = mode_record
    return modes


__all__ = ["merge_capability_recall_rows"]
