"""Read-only projection of context-selection shadow comparisons."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from fdai.core.working_context import ContextSelectionEvaluationStore
from fdai.delivery.read_api.routes.panels import PanelQueryError


class ContextSelectionComparisonPanel:
    path = "/context-selection-comparisons"
    name = "context-selection-comparisons"

    def __init__(self, store: ContextSelectionEvaluationStore) -> None:
        self._store = store

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        try:
            limit = int(params.get("limit", "100"))
        except ValueError as exc:
            raise PanelQueryError("limit MUST be an integer") from exc
        if not 1 <= limit <= 200:
            raise PanelQueryError("limit MUST be in [1, 200]")
        records = await self._store.list(limit=limit)
        return {
            "read_only": True,
            "count": len(records),
            "invariant_failures": sum(record.failure_reason is not None for record in records),
            "comparisons": [
                {
                    "evaluation_id": record.evaluation_id,
                    "input_fingerprint": record.input_fingerprint,
                    "baseline_policy_ref": record.baseline_policy_ref,
                    "candidate_policy_ref": record.candidate_policy_ref,
                    "baseline_manifest": asdict(record.baseline_manifest),
                    "candidate_manifest": (
                        asdict(record.candidate_manifest)
                        if record.candidate_manifest is not None
                        else None
                    ),
                    "baseline_tokens": record.baseline_tokens,
                    "candidate_tokens": record.candidate_tokens,
                    "evidence_overlap": record.evidence_overlap,
                    "omissions": list(record.omissions),
                    "pinned_preserved": record.pinned_preserved,
                    "relevance": record.relevance,
                    "answer_quality_ref": record.answer_quality_ref,
                    "answer_quality_score": record.answer_quality_score,
                    "latency_ms": record.latency_ms,
                    "failure_reason": record.failure_reason,
                    "created_at": record.created_at.isoformat(),
                }
                for record in records
            ],
            "mutation_controls": False,
        }


__all__ = ["ContextSelectionComparisonPanel"]
