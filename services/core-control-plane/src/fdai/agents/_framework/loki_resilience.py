"""Strict normalized-event boundary for Loki-owned resilience candidates."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from fdai.agents._framework.cross_vertical_candidates import (
    validate_cross_vertical_candidate,
)

RESILIENCE_SCORE_EVENT = "specialist.resilience_score"


def resilience_score_candidate(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """Build one owner-authenticated candidate without granting action authority."""
    if event.get("producer_principal") != "Huginn":
        return None
    attributes = event.get("attributes")
    if event.get("event_type") != RESILIENCE_SCORE_EVENT or not isinstance(attributes, Mapping):
        return None
    score = attributes.get("score")
    if isinstance(score, bool) or not isinstance(score, int | float):
        return None
    normalized_score = float(score)
    if not math.isfinite(normalized_score) or not 0.0 <= normalized_score <= 1.0:
        return None

    candidate = {
        "kind": "cross_vertical_candidate",
        "producer_principal": "Loki",
        "correlation_id": event.get("correlation_id"),
        "idempotency_key": event.get("idempotency_key"),
        "resource_id": attributes.get("resource_id") or event.get("resource_id"),
        "observed_at": event.get("occurred_at") or event.get("ingested_at"),
        "score": normalized_score,
        "action_type": attributes.get("action_type"),
        "effects": attributes.get("effects"),
        "evidence_refs": attributes.get("evidence_refs"),
        "source_freshness": attributes.get("source_freshness"),
    }
    try:
        validate_cross_vertical_candidate("object.resilience-score", candidate)
    except (TypeError, ValueError):
        return None
    return candidate


__all__ = ["RESILIENCE_SCORE_EVENT", "resilience_score_candidate"]
