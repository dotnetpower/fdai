"""Bounded cost evidence annotations for Forseti-owned verdicts."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

_MAX_EVIDENCE_ITEMS = 8
_MAX_TEXT = 256
_USD = "USD"


def unavailable_cost_annotation(reason: str = "cost_evidence_unavailable") -> dict[str, Any]:
    """Return the explicit missing-cost state; missing evidence is never zero."""

    return {
        "schema_version": "1.0.0",
        "state": "unavailable",
        "reason": _bounded_text(reason, default="cost_evidence_unavailable"),
        "source_principal": "Njord",
        "freshness_state": "unavailable",
        "observed_at": "",
        "estimate": None,
        "currency": _USD,
        "evidence_refs": [],
        "evidence_digests": [],
    }


def cost_annotation_from_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize optional Njord cost evidence carried by a judgment input."""

    raw = event.get("cost_annotation")
    if isinstance(raw, Mapping):
        normalized = _normalize_raw_cost_annotation(raw)
        if normalized is not None:
            return normalized
        return unavailable_cost_annotation("invalid_cost_annotation")
    if str(event.get("producer_principal") or "") == "Njord" or event.get("evidence_ref"):
        return _annotation_from_njord_signal(event)
    return unavailable_cost_annotation()


def cost_annotation_for_arbitration(
    cost_annotation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a safe arbitration annotation without silently dropping missing evidence."""

    if cost_annotation is None:
        return unavailable_cost_annotation()
    normalized = _normalize_raw_cost_annotation(cost_annotation)
    if normalized is None:
        return unavailable_cost_annotation("invalid_cost_annotation")
    return normalized


def _annotation_from_njord_signal(signal: Mapping[str, Any]) -> dict[str, Any]:
    observed_at = str(signal.get("observed_at") or signal.get("detected_at") or "")
    estimate_value = _finite_float(
        signal.get("monthly_delta_usd", signal.get("variance", signal.get("amount_usd")))
    )
    if estimate_value is None or not observed_at:
        return unavailable_cost_annotation("cost_estimate_incomplete")
    evidence_ref = _bounded_text(signal.get("evidence_ref"), default="")
    evidence_digest = _bounded_text(
        signal.get("evidence_digest") or signal.get("idempotency_key") or signal.get("id"),
        default="",
    )
    return {
        "schema_version": "1.0.0",
        "state": "measured",
        "reason": "",
        "source_principal": "Njord",
        "freshness_state": "fresh",
        "observed_at": _bounded_text(observed_at, default=""),
        "estimate": {"monthly_delta": estimate_value, "currency": _USD},
        "currency": _USD,
        "evidence_refs": [evidence_ref] if evidence_ref else [],
        "evidence_digests": [evidence_digest] if evidence_digest else [],
    }


def _normalize_raw_cost_annotation(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    state = str(raw.get("state") or raw.get("evidence_state") or "").strip()
    if state == "unavailable":
        return unavailable_cost_annotation(str(raw.get("reason") or "cost_evidence_unavailable"))
    if state not in {"measured", "estimated"}:
        return None
    if str(raw.get("source_principal") or "Njord") != "Njord":
        return None
    estimate = raw.get("estimate")
    monthly_delta = None
    if isinstance(estimate, Mapping):
        monthly_delta = _finite_float(estimate.get("monthly_delta"))
    if monthly_delta is None:
        monthly_delta = _finite_float(raw.get("monthly_delta_usd"))
    observed_at = _bounded_text(raw.get("observed_at"), default="")
    if monthly_delta is None or not observed_at:
        return None
    return {
        "schema_version": "1.0.0",
        "state": state,
        "reason": "",
        "source_principal": "Njord",
        "freshness_state": _bounded_text(raw.get("freshness_state"), default="fresh"),
        "observed_at": observed_at,
        "estimate": {"monthly_delta": monthly_delta, "currency": _USD},
        "currency": _USD,
        "evidence_refs": _bounded_text_list(raw.get("evidence_refs")),
        "evidence_digests": _bounded_text_list(raw.get("evidence_digests")),
    }


def _bounded_text_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for item in raw[:_MAX_EVIDENCE_ITEMS]:
        text = _bounded_text(item, default="")
        if text:
            values.append(text)
    return values


def _bounded_text(raw: object, *, default: str) -> str:
    if not isinstance(raw, str):
        return default
    text = raw.strip()
    if not text:
        return default
    return text[:_MAX_TEXT]


def _finite_float(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        try:
            raw = float(str(raw))
        except (TypeError, ValueError):
            return None
    value = float(raw)
    if not math.isfinite(value):
        return None
    return value


__all__ = [
    "cost_annotation_for_arbitration",
    "cost_annotation_from_event",
    "unavailable_cost_annotation",
]
