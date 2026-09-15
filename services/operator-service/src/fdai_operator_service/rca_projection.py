"""Pure audit-to-RCA projection for the independent Operator Service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from fdai_service_contracts import JsonObject

_CAUSE_DOMAINS = frozenset(
    {
        "infrastructure",
        "application",
        "shared_dependency",
        "external_provider",
        "mixed",
        "unknown",
    }
)
_RESPONSE_ACTION_KINDS = frozenset({"risk_gate.shadow_authority", "risk_gate.unified"})
_RESPONSE_DECISIONS = frozenset({"abstain", "auto", "deny", "hil", "shadow"})


def rca_view(correlation_id: str, items: Sequence[JsonObject]) -> JsonObject | None:
    """Project correlated audit evidence into the frozen RCA view envelope."""
    if not items:
        return None
    ordered = sorted(items, key=lambda item: _as_int(item["seq"]))
    hypothesis_rows = [item for item in ordered if item.get("action_kind") == "rca.hypothesis"]
    hypotheses = [_hypothesis(item) for item in reversed(hypothesis_rows)]
    primary_hypothesis = hypothesis_rows[-1] if hypothesis_rows else None
    return cast(
        JsonObject,
        {
            "correlation_id": correlation_id,
            "incident_id": _first_entry_string(ordered, "incident_id"),
            "hypotheses": hypotheses,
            "response": _linked_response(ordered, primary_hypothesis),
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
            "cause_domain": _cause_domain(entry.get("rca_cause_domain")),
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


def _linked_response(
    items: Sequence[JsonObject],
    primary_hypothesis: JsonObject | None,
) -> JsonObject | None:
    if primary_hypothesis is None:
        return None
    hypothesis_entry = _mapping(primary_hypothesis.get("entry"))
    if _nonempty(hypothesis_entry.get("rca_outcome")) != "grounded":
        return None
    hypothesis_seq = _as_int(primary_hypothesis["seq"])
    response_rows = [
        item
        for item in items
        if _as_int(item["seq"]) > hypothesis_seq
        and _response_matches_hypothesis(item, primary_hypothesis)
    ]
    return _response(response_rows, hypothesis_seq=hypothesis_seq)


def _response_matches_hypothesis(
    item: JsonObject,
    hypothesis: JsonObject,
) -> bool:
    if not _has_response_evidence(item):
        return False
    event_id = _record_string(item, "event_id")
    hypothesis_event_id = _record_string(hypothesis, "event_id")
    if event_id is None or event_id != hypothesis_event_id:
        return False
    remediation_ref = _record_string(hypothesis, "rca_remediation_ref")
    return remediation_ref is None or _response_action_type(item) == remediation_ref


def _has_response_evidence(item: JsonObject) -> bool:
    return (
        item.get("action_kind") in _RESPONSE_ACTION_KINDS and _response_decision(item) is not None
    )


def _response(
    items: Sequence[JsonObject],
    *,
    hypothesis_seq: int,
) -> JsonObject | None:
    if not items:
        return None
    latest = items[-1]
    decision = _response_decision(latest)
    if decision is None:
        return None
    return cast(
        JsonObject,
        {
            "hypothesis_seq": hypothesis_seq,
            "source_seq": _as_int(latest["seq"]),
            "verdict": decision,
            "decision": decision,
            "action_kind": str(latest["action_kind"]),
            "action_type_id": _response_action_type(latest),
            "mode": _response_mode(latest),
            "rollback_reference": _first_entry_string(
                (latest,), "rollback_reference", "rollback_ref"
            ),
            "recorded_at": str(latest["recorded_at"]),
        },
    )


def _response_action_type(item: JsonObject) -> str | None:
    entry = _mapping(item.get("entry"))
    return _nonempty(entry.get("action_type_id"))


def _response_mode(item: JsonObject) -> str | None:
    entry = _mapping(item.get("entry"))
    mode = _nonempty(entry.get("effective_mode"))
    return mode if mode in {"shadow", "enforce"} else None


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


def _response_decision(item: JsonObject) -> str | None:
    entry = _mapping(item.get("entry"))
    decisions = {
        decision
        for key in ("decision", "gate_decision")
        if (decision := _canonical_response_decision(entry.get(key))) is not None
    }
    return decisions.pop() if len(decisions) == 1 else None


def _canonical_response_decision(value: object) -> str | None:
    decision = (_nonempty(value) or "").lower()
    return decision if decision in _RESPONSE_DECISIONS else None


def _first_entry_string(items: Sequence[JsonObject], *keys: str) -> str | None:
    for item in items:
        entry = _mapping(item.get("entry"))
        for key in keys:
            if value := _nonempty(entry.get(key)):
                return value
    return None


def _record_string(item: JsonObject, key: str) -> str | None:
    return _nonempty(item.get(key)) or _nonempty(_mapping(item.get("entry")).get(key))


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mappings(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _nonempty(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _cause_domain(value: object) -> str:
    domain = _nonempty(value)
    return domain if domain in _CAUSE_DOMAINS else "unknown"


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _as_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("projection sequence MUST be an integer")
    return value


__all__ = ["rca_view"]
