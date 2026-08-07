"""Pure audit-to-RCA projection for the independent Operator Service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from fdai_service_contracts import JsonObject


def rca_view(correlation_id: str, items: Sequence[JsonObject]) -> JsonObject | None:
    """Project correlated audit evidence into the frozen RCA view envelope."""
    if not items:
        return None
    ordered = sorted(items, key=lambda item: _as_int(item["seq"]))
    hypotheses = [
        _hypothesis(item)
        for item in reversed(ordered)
        if item.get("action_kind") == "rca.hypothesis"
    ]
    action_rows = [item for item in ordered if item.get("action_kind") != "rca.hypothesis"]
    return cast(
        JsonObject,
        {
            "correlation_id": correlation_id,
            "incident_id": _first_entry_string(ordered, "incident_id"),
            "hypotheses": hypotheses,
            "response": _response(action_rows),
        },
    )


def _hypothesis(item: JsonObject) -> JsonObject:
    entry = _mapping(item.get("entry"))
    outcome = _nonempty(entry.get("rca_outcome")) or "unknown"
    citations = [
        {"kind": kind, "ref": ref}
        for value in _mappings(entry.get("rca_citations"))
        if (kind := _nonempty(value.get("kind"))) and (ref := _nonempty(value.get("ref")))
    ]
    return cast(
        JsonObject,
        {
            "seq": _as_int(item["seq"]),
            "tier": _nonempty(entry.get("rca_tier")) or "unknown",
            "outcome": outcome,
            "grounded": outcome == "grounded",
            "cause": _nonempty(entry.get("rca_cause")),
            "confidence": _number(entry.get("rca_confidence")),
            "reason": _nonempty(entry.get("rca_reason")),
            "citations": citations,
            "remediation_ref": _nonempty(entry.get("rca_remediation_ref")),
            "causal_chain": _causal_chain(entry.get("rca_causal_chain")),
            "mode": str(item["mode"]),
            "recorded_at": str(item["recorded_at"]),
        },
    )


def _response(items: Sequence[JsonObject]) -> JsonObject | None:
    if not items:
        return None
    latest = items[-1]
    newest = list(reversed(items))
    return cast(
        JsonObject,
        {
            "verdict": _verdict(newest),
            "decision": _first_entry_string(newest, "decision", "gate_decision"),
            "action_kind": str(latest["action_kind"]),
            "mode": str(latest["mode"]),
            "rollback_reference": _first_entry_string(newest, "rollback_reference", "rollback_ref"),
            "recorded_at": str(latest["recorded_at"]),
        },
    )


def _causal_chain(raw: object) -> JsonObject | None:
    chain = _mapping(raw)
    root = _nonempty(chain.get("root_event_id"))
    failure = _nonempty(chain.get("failure_event_id"))
    confidence = _number(chain.get("confidence"))
    ambiguity = _integer(chain.get("ambiguity"))
    hops = _mappings(chain.get("hops"))
    if not root or not failure or confidence is None or not ambiguity or not hops:
        return None
    projected: list[JsonObject] = []
    for hop in hops:
        required = [
            _nonempty(hop.get(key))
            for key in (
                "cause_event_id",
                "effect_event_id",
                "cause_resource_ref",
                "effect_resource_ref",
                "relationship",
            )
        ]
        lead = _number(hop.get("lead_seconds"))
        hop_confidence = _number(hop.get("confidence"))
        if any(value is None for value in required) or lead is None or hop_confidence is None:
            return None
        projected.append(
            cast(
                JsonObject,
                {
                    "cause_event_id": required[0] or "",
                    "effect_event_id": required[1] or "",
                    "cause_resource_ref": required[2] or "",
                    "effect_resource_ref": required[3] or "",
                    "lead_seconds": lead,
                    "relationship": required[4] or "",
                    "confidence": hop_confidence,
                },
            )
        )
    return cast(
        JsonObject,
        {
            "root_event_id": root,
            "failure_event_id": failure,
            "confidence": confidence,
            "ambiguity": ambiguity,
            "hops": projected,
        },
    )


def _verdict(items: Sequence[JsonObject]) -> str:
    for item in items:
        entry = _mapping(item.get("entry"))
        tokens = {
            str(item.get("action_kind") or "").lower(),
            str(entry.get("decision") or "").lower(),
            str(entry.get("gate_decision") or "").lower(),
            str(entry.get("outcome") or "").lower(),
            str(entry.get("status") or "").lower(),
        }
        for verdict in ("auto", "hil", "deny", "abstain"):
            if verdict in tokens or (verdict == "abstain" and "abstained" in tokens):
                return verdict
    return "unknown"


def _first_entry_string(items: Sequence[JsonObject], *keys: str) -> str | None:
    for item in items:
        entry = _mapping(item.get("entry"))
        for key in keys:
            if value := _nonempty(entry.get(key)):
                return value
    return None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mappings(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _nonempty(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _as_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("projection sequence MUST be an integer")
    return value


__all__ = ["rca_view"]
