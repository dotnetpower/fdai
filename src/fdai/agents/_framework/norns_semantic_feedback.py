"""Deterministic Norns intake for reproduced semantic retrieval failures."""

from __future__ import annotations

from typing import Any

from fdai.agents._framework.bounded import BoundedLruSet
from fdai.rule_catalog.schema.rule_semantic_feedback import (
    SemanticFeedbackCandidateSink,
    build_feedback_candidate,
    query_failure_evidence_from_mapping,
)

_MAX_TRACKED = 50_000


class NornsSemanticFeedbackLearning:
    """Persist exact challengers before producing inert RuleCandidate mappings."""

    def __init__(self, sink: SemanticFeedbackCandidateSink | None) -> None:
        self._sink = sink
        self._proposed: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)

    async def observe(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if payload.get("producer_principal") != "Muninn":
            raise ValueError("semantic retrieval failure MUST be published by Muninn")
        raw = payload.get("failure")
        if not isinstance(raw, dict):
            raise ValueError("semantic retrieval failure MUST contain a failure object")
        evidence = query_failure_evidence_from_mapping(raw)
        candidate = build_feedback_candidate(evidence)
        if self._sink is None:
            raise RuntimeError("semantic feedback candidate sink is unavailable")
        await self._sink.put(candidate)
        if candidate.candidate_id in self._proposed:
            return None
        proposal = {
            "source_signal": "semantic_retrieval_failure",
            "evidence": {
                "candidate_id": candidate.candidate_id,
                "attempt_id": candidate.attempt_id,
                "query_digest": candidate.query_digest,
                "failure_layer": candidate.failure_layer.value,
                "evidence_refs": list(candidate.evidence_refs),
                "mode": candidate.mode,
                "promotion_authority": candidate.promotion_authority,
            },
            "proposed_by": "Norns",
            "proposal_kind": "revision",
            "suggested_change": "review_semantic_surface",
            "target_rule_id": _target_rule_id(candidate.target_rule_ref),
        }
        self._proposed.add(candidate.candidate_id)
        return proposal


def _target_rule_id(rule_ref: str) -> str:
    if not rule_ref.startswith("rule:") or "@" not in rule_ref:
        raise ValueError("semantic feedback target MUST be an exact versioned Rule ref")
    rule_id, version = rule_ref.removeprefix("rule:").rsplit("@", 1)
    if not rule_id or not version:
        raise ValueError("semantic feedback target MUST be an exact versioned Rule ref")
    return rule_id


__all__ = ["NornsSemanticFeedbackLearning"]
