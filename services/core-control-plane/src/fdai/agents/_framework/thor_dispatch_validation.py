"""Pure validation helpers for Thor verdict dispatch."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from fdai.core.executor.safeguards import (
    AUDIT_INTENT,
    BLAST_RADIUS,
    DRY_RUN_RECEIPT,
    IDEMPOTENCY_KEY,
    ROLLBACK,
    SEVEN_SAFEGUARDS,
    STOP_CONDITION,
    TARGET_LOCK,
)
from fdai.shared.contracts.models import Autonomy

_MAX_PARAMS_BYTES = 16_384
_MAX_MAPPING_KEYS = 64
_MAX_LIST_ITEMS = 64
_MAX_STRING_CHARS = 2_048
_MAX_DEPTH = 6

_WIRE_SAFEGUARD_FIELDS: dict[str, tuple[str, ...]] = {
    STOP_CONDITION: ("stop_condition", "stop_conditions"),
    ROLLBACK: ("tested_rollback_contract", "rollback_contract_tested", "rollback_receipt"),
    BLAST_RADIUS: ("blast_radius_limit", "blast_radius"),
    DRY_RUN_RECEIPT: ("dry_run_receipt", "what_if_receipt"),
    TARGET_LOCK: ("logical_target_lock", "target_lock"),
    IDEMPOTENCY_KEY: ("stable_idempotency_key", "action_idempotency_key", "idempotency_key"),
    AUDIT_INTENT: ("two_phase_audit_intent", "audit_intent"),
}


def resolved_autonomy_ceiling(verdict: Mapping[str, Any]) -> Autonomy:
    """Return the most restrictive typed ceiling carried by one verdict."""
    values: list[Autonomy] = []
    raw = verdict.get("resolved_autonomy_ceiling")
    if raw is not None:
        if not isinstance(raw, str):
            return Autonomy.SHADOW_ONLY
        try:
            values.append(Autonomy(raw))
        except ValueError:
            return Autonomy.SHADOW_ONLY
    operational_context = verdict.get("operational_context")
    if operational_context is not None:
        if not isinstance(operational_context, Mapping):
            return Autonomy.SHADOW_ONLY
        context_ceiling = operational_context.get("autonomy_ceiling")
        if not isinstance(context_ceiling, str):
            return Autonomy.SHADOW_ONLY
        try:
            values.append(Autonomy(context_ceiling))
        except ValueError:
            return Autonomy.SHADOW_ONLY
    if not values:
        return Autonomy.SHADOW_ONLY
    rank = {
        Autonomy.SHADOW_ONLY: 0,
        Autonomy.ENFORCE_HIL: 1,
        Autonomy.ENFORCE_AUTO: 2,
    }
    return min(values, key=rank.__getitem__)


def selected_action_matches(decision_case: Mapping[str, Any], action_type: str) -> bool:
    """Check that the selected bounded option names the dispatched ActionType."""
    selected = decision_case.get("selected_option_id")
    options = decision_case.get("options")
    if not isinstance(selected, str) or not isinstance(options, list):
        return False
    return any(
        isinstance(option, Mapping)
        and option.get("option_id") == selected
        and option.get("action_type") == action_type
        and isinstance(option.get("effects"), list)
        and bool(option["effects"])
        for option in options
    )


def bounded_params(raw: object) -> dict[str, Any] | None:
    """Return bounded canonical params or ``None`` for untrusted oversized input."""

    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        return None
    candidate = _bounded_value(raw, depth=0)
    if not isinstance(candidate, dict):
        return None
    try:
        encoded = json.dumps(
            candidate,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        return None
    if len(encoded.encode("utf-8")) > _MAX_PARAMS_BYTES:
        return None
    return deepcopy(candidate)


def missing_wire_safeguards(verdict: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the seven-safeguard ids missing from one executable verdict."""

    carrier = verdict.get("safeguards")
    if not isinstance(carrier, Mapping):
        carrier = verdict.get("kinetic_proposal")
        carrier = carrier.get("safeguards") if isinstance(carrier, Mapping) else {}
    carriers = (verdict, carrier if isinstance(carrier, Mapping) else {})
    missing: list[str] = []
    for safeguard in SEVEN_SAFEGUARDS:
        fields = _WIRE_SAFEGUARD_FIELDS[safeguard]
        if not any(_present(mapping.get(field)) for mapping in carriers for field in fields):
            missing.append(safeguard)
    return tuple(missing)


def dry_run_obligation_only(verdict: Mapping[str, Any]) -> bool:
    """Return whether the verdict's dry-run safeguard is a declared obligation, not a receipt."""

    carrier = verdict.get("safeguards")
    return isinstance(carrier, Mapping) and carrier.get("dry_run_evidence") == (
        "declared_obligation"
    )


def _bounded_value(value: object, *, depth: int) -> object | None:
    if depth > _MAX_DEPTH:
        return None
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        return normalized if len(normalized) <= _MAX_STRING_CHARS else None
    if isinstance(value, Mapping):
        if len(value) > _MAX_MAPPING_KEYS:
            return None
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip() or len(key) > 128:
                return None
            bounded = _bounded_value(item, depth=depth + 1)
            if bounded is None and item is not None:
                return None
            result[key.strip()] = bounded
        return result
    if isinstance(value, list | tuple):
        if len(value) > _MAX_LIST_ITEMS:
            return None
        sequence_result: list[object | None] = []
        for item in value:
            bounded = _bounded_value(item, depth=depth + 1)
            if bounded is None and item is not None:
                return None
            sequence_result.append(bounded)
        return sequence_result
    return None


def _present(value: object) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping | list | tuple | set):
        return bool(value)
    return True


__all__ = [
    "bounded_params",
    "dry_run_obligation_only",
    "missing_wire_safeguards",
    "resolved_autonomy_ceiling",
    "selected_action_matches",
]
