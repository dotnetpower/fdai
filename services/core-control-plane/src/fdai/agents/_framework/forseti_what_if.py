"""Versioned retrospective what-if replay helpers for Forseti."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.forseti_judgment import JudgmentTable

CONTRACT_VERSION = "retrospective-what-if.v1"
MAX_WHAT_IF_SAMPLES = 32


@dataclass(frozen=True, slots=True)
class WhatIfBatch:
    payload: dict[str, Any]
    idempotency_keys: tuple[str, ...]


def judgment_table_from_request(raw: object) -> JudgmentTable | None:
    """Build a bounded alternate table from a typed request payload."""

    if not isinstance(raw, Mapping):
        return None
    rule_match = _bounded_str_mapping(raw.get("rule_match"))
    risk_verdict = _bounded_str_mapping(raw.get("risk_verdict"))
    source = str(raw.get("source") or "typed-retrospective-what-if")
    if rule_match is None or risk_verdict is None or len(source) > 128:
        return None
    return JudgmentTable(rule_match=rule_match, risk_verdict=risk_verdict, source=source)


def build_what_if_batch(
    *,
    correlation_id: str,
    active_table: JudgmentTable,
    what_if_table: JudgmentTable,
    retained_samples: Iterable[tuple[str, Mapping[str, str]]],
    sample_limit: int,
) -> WhatIfBatch | None:
    """Replay a bounded retained sample window and return inert evidence."""

    limit = max(1, min(sample_limit, MAX_WHAT_IF_SAMPLES))
    outcomes: list[dict[str, Any]] = []
    idempotency_keys: list[str] = []
    for key, sample in tuple(retained_samples)[-limit:]:
        event_type = str(sample.get("event_type") or "")
        original_action = str(sample.get("action_type") or "")
        original_verdict = str(sample.get("risk_verdict") or "")
        input_digest = _input_digest(key, sample)
        active_action = original_action or active_table.rule_match.get(event_type, "")
        what_if_action = what_if_table.rule_match.get(event_type, active_action)
        what_if_verdict = what_if_table.risk_verdict.get(what_if_action, "hil")
        reason_codes = _reason_codes(
            original_action=active_action,
            what_if_action=what_if_action,
            original_verdict=original_verdict,
            what_if_verdict=what_if_verdict,
        )
        idempotency_keys.append("|".join((CONTRACT_VERSION, what_if_table.digest, input_digest)))
        outcomes.append(
            {
                "input_digest": input_digest,
                "original": {
                    "action_type": active_action,
                    "risk_verdict": original_verdict,
                    "judgment_table_digest": active_table.digest,
                },
                "what_if": {
                    "action_type": what_if_action,
                    "risk_verdict": what_if_verdict,
                    "judgment_table_digest": what_if_table.digest,
                },
                "disagrees": bool(reason_codes),
                "reason_codes": reason_codes,
            }
        )
    if not outcomes:
        return None
    payload = {
        "producer_principal": "Forseti",
        "kind": "retrospective_what_if",
        "correlation_id": correlation_id,
        "resource_id": "retrospective-what-if",
        "action_type": "",
        "risk_verdict": "hil",
        "resolved_autonomy_ceiling": "shadow_only",
        "reason": "retrospective_what_if_evidence",
        "quorum_required": 1,
        "what_if_contract": {
            "contract_version": CONTRACT_VERSION,
            "active_judgment_table_digest": active_table.digest,
            "what_if_judgment_table_digest": what_if_table.digest,
            "sample_limit": limit,
            "selection": "recent_retained_judgment_inputs",
        },
        "outcomes": outcomes,
        "disagreement_count": sum(1 for outcome in outcomes if outcome["disagrees"]),
    }
    return WhatIfBatch(payload=payload, idempotency_keys=tuple(idempotency_keys))


def _bounded_str_mapping(raw: object) -> dict[str, str] | None:
    if not isinstance(raw, Mapping) or len(raw) > 128:
        return None
    result: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key).strip()
        item = str(value).strip()
        if not name or not item or len(name) > 128 or len(item) > 128:
            return None
        result[name] = item
    return result


def _input_digest(key: str, sample: Mapping[str, str]) -> str:
    encoded = json.dumps(
        {"key": key, "sample": dict(sorted(sample.items()))},
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _reason_codes(
    *,
    original_action: str,
    what_if_action: str,
    original_verdict: str,
    what_if_verdict: str,
) -> list[str]:
    reasons: list[str] = []
    if original_action != what_if_action:
        reasons.append("action_type_changed")
    if original_verdict != what_if_verdict:
        reasons.append("risk_verdict_changed")
    return reasons


__all__ = [
    "CONTRACT_VERSION",
    "MAX_WHAT_IF_SAMPLES",
    "WhatIfBatch",
    "build_what_if_batch",
    "judgment_table_from_request",
]
