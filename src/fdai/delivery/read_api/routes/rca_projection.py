"""Pure audit-to-RCA read projection for the operator console.

Projects the shadow ``rca.hypothesis`` audit entries that the control
loop appends (see
:meth:`fdai.core.control_loop.orchestrator.ControlLoopOrchestrator._analyze_and_audit_rca`)
into a per-incident RCA view: the tiered root-cause hypotheses with their
grounded citations, plus the linked response / remediation plan composed
from the same correlated audit stream.

An RCA hypothesis is a **hypothesis with citations**, never an
authoritative verdict. An ungrounded / abstained hypothesis is surfaced
explicitly so the console renders "insufficient grounding -> HIL", never a
confident cause. Execution eligibility stays with the risk gate + verifier.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from fdai.delivery.read_api.read_model import (
    AuditItem,
    RcaCausalChainView,
    RcaCausalHopView,
    RcaCitationView,
    RcaHypothesisView,
    RcaResponsePlan,
    RcaView,
)

_RCA_ACTION_KIND = "rca.hypothesis"
_GROUNDED_OUTCOME = "grounded"


def project_rca(items: Iterable[AuditItem], *, correlation_id: str) -> RcaView:
    """Project correlated audit rows into one incident's RCA view.

    ``items`` are the audit rows already correlated to ``correlation_id``
    (as returned by ``ConsoleReadModel.list_audit(correlation_id=...)``);
    order is irrelevant - this function sorts by ``seq``.
    """
    ordered = sorted(items, key=lambda item: item.seq)
    hypotheses = tuple(
        _project_hypothesis(item)
        for item in reversed(ordered)
        if item.action_kind == _RCA_ACTION_KIND
    )
    incident_id = _first_string(ordered, "incident_id")
    response = _project_response(ordered)
    return RcaView(
        correlation_id=correlation_id,
        incident_id=incident_id,
        hypotheses=hypotheses,
        response=response,
    )


def _project_hypothesis(item: AuditItem) -> RcaHypothesisView:
    entry = item.entry
    outcome = _string(entry, "rca_outcome") or "unknown"
    return RcaHypothesisView(
        seq=item.seq,
        tier=_string(entry, "rca_tier") or "unknown",
        outcome=outcome,
        grounded=outcome == _GROUNDED_OUTCOME,
        cause=_string(entry, "rca_cause"),
        confidence=_float(entry, "rca_confidence"),
        reason=_string(entry, "rca_reason"),
        citations=_project_citations(entry.get("rca_citations")),
        remediation_ref=_string(entry, "rca_remediation_ref"),
        causal_chain=_project_causal_chain(entry.get("rca_causal_chain")),
        mode=item.mode,
        recorded_at=item.recorded_at,
    )


def _project_citations(raw: Any) -> tuple[RcaCitationView, ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ()
    citations: list[RcaCitationView] = []
    for candidate in raw:
        if not isinstance(candidate, Mapping):
            continue
        kind = _string(candidate, "kind")
        ref = _string(candidate, "ref")
        if kind and ref:
            citations.append(RcaCitationView(kind=kind, ref=ref))
    return tuple(citations)


def _project_causal_chain(raw: Any) -> RcaCausalChainView | None:
    if not isinstance(raw, Mapping):
        return None
    root_event_id = _string(raw, "root_event_id")
    failure_event_id = _string(raw, "failure_event_id")
    confidence = _float(raw, "confidence")
    ambiguity = _int(raw, "ambiguity")
    raw_hops = raw.get("hops")
    if (
        not root_event_id
        or not failure_event_id
        or confidence is None
        or ambiguity is None
        or ambiguity < 1
        or not isinstance(raw_hops, Sequence)
        or isinstance(raw_hops, (str, bytes))
    ):
        return None
    hops: list[RcaCausalHopView] = []
    for candidate in raw_hops:
        hop = _project_causal_hop(candidate)
        if hop is None:
            return None
        hops.append(hop)
    if not hops:
        return None
    return RcaCausalChainView(
        root_event_id=root_event_id,
        failure_event_id=failure_event_id,
        confidence=confidence,
        ambiguity=ambiguity,
        hops=tuple(hops),
    )


def _project_causal_hop(raw: Any) -> RcaCausalHopView | None:
    if not isinstance(raw, Mapping):
        return None
    strings = {
        key: _string(raw, key)
        for key in (
            "cause_event_id",
            "effect_event_id",
            "cause_resource_ref",
            "effect_resource_ref",
            "relationship",
        )
    }
    lead_seconds = _float(raw, "lead_seconds")
    confidence = _float(raw, "confidence")
    if (
        any(value is None for value in strings.values())
        or lead_seconds is None
        or confidence is None
    ):
        return None
    return RcaCausalHopView(
        cause_event_id=strings["cause_event_id"] or "",
        effect_event_id=strings["effect_event_id"] or "",
        cause_resource_ref=strings["cause_resource_ref"] or "",
        effect_resource_ref=strings["effect_resource_ref"] or "",
        lead_seconds=lead_seconds,
        relationship=strings["relationship"] or "",
        confidence=confidence,
    )


def _project_response(ordered: Sequence[AuditItem]) -> RcaResponsePlan | None:
    """Compose the linked response plan from non-RCA audit rows.

    The RCA rows explain "why"; the response plan reflects what the
    pipeline decided (verdict / delivered action / mode / rollback). It is
    a read-only reflection, never a new decision.
    """
    action_rows = [item for item in ordered if item.action_kind != _RCA_ACTION_KIND]
    if not action_rows:
        return None
    latest_first = tuple(reversed(action_rows))
    verdict = _verdict(latest_first)
    decision = _first_string_from_entries(latest_first, "decision", "gate_decision")
    rollback = _first_string_from_entries(latest_first, "rollback_reference", "rollback_ref")
    latest = latest_first[0]
    return RcaResponsePlan(
        verdict=verdict,
        decision=decision,
        action_kind=latest.action_kind,
        mode=latest.mode,
        rollback_reference=rollback,
        recorded_at=latest.recorded_at,
    )


def _verdict(items_latest_first: Sequence[AuditItem]) -> str:
    for item in items_latest_first:
        tokens = _tokens(item)
        for verdict in ("auto", "hil", "deny", "abstain"):
            if verdict in tokens or (verdict == "abstain" and "abstained" in tokens):
                return verdict
    return "unknown"


def _tokens(item: AuditItem) -> set[str]:
    entry = item.entry
    values = {
        item.action_kind.lower(),
        (_string(entry, "decision") or "").lower(),
        (_string(entry, "gate_decision") or "").lower(),
        (_string(entry, "outcome") or "").lower(),
        (_string(entry, "status") or "").lower(),
    }
    return {value for value in values if value}


def _first_string_from_entries(items: Sequence[AuditItem], *keys: str) -> str | None:
    for item in items:
        for key in keys:
            value = _string(item.entry, key)
            if value:
                return value
    return None


def _first_string(items: Sequence[AuditItem], *keys: str) -> str | None:
    for item in items:
        for key in keys:
            value = _string(item.entry, key)
            if value:
                return value
    return None


def _string(entry: Mapping[str, Any], key: str) -> str | None:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _float(entry: Mapping[str, Any], key: str) -> float | None:
    value = entry.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _int(entry: Mapping[str, Any], key: str) -> int | None:
    value = entry.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = ["project_rca"]
