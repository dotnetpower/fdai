"""Read-only root-cause analysis projection contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RcaCitationView:
    kind: str
    ref: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ref": self.ref}


@dataclass(frozen=True, slots=True)
class RcaCausalHopView:
    cause_event_id: str
    effect_event_id: str
    cause_resource_ref: str
    effect_resource_ref: str
    lead_seconds: float
    relationship: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RcaCausalChainView:
    root_event_id: str
    failure_event_id: str
    confidence: float
    ambiguity: int
    hops: Sequence[RcaCausalHopView]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_event_id": self.root_event_id,
            "failure_event_id": self.failure_event_id,
            "confidence": self.confidence,
            "ambiguity": self.ambiguity,
            "hops": [hop.to_dict() for hop in self.hops],
        }


@dataclass(frozen=True, slots=True)
class RcaHypothesisView:
    seq: int
    tier: str
    outcome: str
    grounded: bool
    cause: str | None
    confidence: float | None
    reason: str | None
    citations: Sequence[RcaCitationView]
    remediation_ref: str | None
    causal_chain: RcaCausalChainView | None
    mode: str
    recorded_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "tier": self.tier,
            "outcome": self.outcome,
            "grounded": self.grounded,
            "cause": self.cause,
            "confidence": self.confidence,
            "reason": self.reason,
            "citations": [citation.to_dict() for citation in self.citations],
            "remediation_ref": self.remediation_ref,
            "causal_chain": self.causal_chain.to_dict() if self.causal_chain else None,
            "mode": self.mode,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class RcaResponsePlan:
    verdict: str
    decision: str | None
    action_kind: str | None
    mode: str | None
    rollback_reference: str | None
    recorded_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RcaView:
    correlation_id: str
    incident_id: str | None
    hypotheses: Sequence[RcaHypothesisView]
    response: RcaResponsePlan | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "incident_id": self.incident_id,
            "hypotheses": [hypothesis.to_dict() for hypothesis in self.hypotheses],
            "response": self.response.to_dict() if self.response else None,
        }


__all__ = [
    "RcaCausalChainView",
    "RcaCausalHopView",
    "RcaCitationView",
    "RcaHypothesisView",
    "RcaResponsePlan",
    "RcaView",
]
