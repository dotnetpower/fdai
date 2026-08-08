"""Purpose-scoped case cohort analysis for Norns off-path review."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from typing import Protocol

from fdai.core.learning import (
    NoImprovement,
    PostTurnProposal,
    PostTurnReviewInput,
    RuleCandidateHint,
)
from fdai.shared.providers.case_history import (
    CaseHistoryArtifactStore,
    CaseHistoryMetadataStore,
    CaseHistoryRevisionRecord,
)

_FAILURE_LABELS = (
    "false_positive",
    "false_negative",
    "late_breach",
    "magnitude_error",
)
_CONTROL_LABELS = (
    "true_positive",
    "intervention_censored",
    "unscorable",
)
_MAX_REVIEW_BODY_CHARS = 12_000


class CaseHistoryReviewer(Protocol):
    async def review(
        self,
        review_input: PostTurnReviewInput,
    ) -> PostTurnProposal | NoImprovement: ...


class CaseHistoryAnalyzer:
    """Build bounded failure/control case cards and request an inert rule hint."""

    def __init__(
        self,
        *,
        metadata: CaseHistoryMetadataStore,
        artifacts: CaseHistoryArtifactStore,
        reviewer: CaseHistoryReviewer,
        failure_limit: int = 12,
        control_limit: int = 6,
        artifact_concurrency: int = 4,
        artifact_timeout_seconds: float = 5.0,
    ) -> None:
        if not 1 <= failure_limit <= 50 or not 1 <= control_limit <= 50:
            raise ValueError("case history cohort limits MUST be in [1, 50]")
        if not 1 <= artifact_concurrency <= 16 or artifact_timeout_seconds <= 0:
            raise ValueError("case history artifact I/O bounds are invalid")
        self._metadata = metadata
        self._artifacts = artifacts
        self._reviewer = reviewer
        self._failure_limit = failure_limit
        self._control_limit = control_limit
        self._artifact_concurrency = artifact_concurrency
        self._artifact_timeout_seconds = artifact_timeout_seconds

    async def analyze(self, index_event: Mapping[str, object]) -> RuleCandidateHint | None:
        if index_event.get("kind") != "forecast_case_history":
            return None
        scope = _required(index_event, "access_scope_digest")
        purpose = _required(index_event, "purpose")
        detector_id = _required(index_event, "detector_id")
        metric = _required(index_event, "metric")
        failures = await self._metadata.list_closed(
            access_scope_digest=scope,
            purpose=purpose,
            outcome_labels=_FAILURE_LABELS,
            detector_id=detector_id,
            metric=metric,
            limit=self._failure_limit,
        )
        controls = await self._metadata.list_closed(
            access_scope_digest=scope,
            purpose=purpose,
            outcome_labels=_CONTROL_LABELS,
            detector_id=detector_id,
            metric=metric,
            limit=self._control_limit,
        )
        selected = (*failures, *controls)
        if not failures or not selected:
            return None
        semaphore = asyncio.Semaphore(self._artifact_concurrency)

        async def load(record: CaseHistoryRevisionRecord) -> dict[str, object] | None:
            async with semaphore:
                try:
                    return await asyncio.wait_for(
                        self._card(record, metric=metric),
                        timeout=self._artifact_timeout_seconds,
                    )
                except (TimeoutError, ValueError):
                    return None

        loaded = await asyncio.gather(*(load(record) for record in selected))
        if any(card is None for card in loaded):
            return None
        cards = [card for card in loaded if card is not None]
        encoded = json.dumps(cards, sort_keys=True, separators=(",", ":"))
        if len(encoded) > _MAX_REVIEW_BODY_CHARS:
            return None
        evidence_refs = [_evidence_ref(record) for record in selected]
        if not cards or not any(card["cohort"] == "failure" for card in cards):
            return None
        body = json.dumps(
            {
                "trusted": False,
                "detector_id": detector_id,
                "metric": metric,
                "case_cards": cards,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        review_digest = hashlib.sha256(body.encode()).hexdigest()
        review_input = PostTurnReviewInput(
            review_id=f"case-review-{review_digest[:32]}",
            principal_scope=scope,
            operator_turn_id=f"case-cohort-{review_digest[:24]}",
            assistant_turn_id=f"case-analysis-{review_digest[:24]}",
            completed_at=max(record.sealed_at for record in selected),
            assistant_body=body,
            validation_outcomes=tuple(sorted({record.outcome_label for record in selected})),
            evidence_refs=tuple(evidence_refs),
            failure_recovered=False,
            procedure_fingerprint=f"forecast-{review_digest[:32]}",
            repeated_procedure_count=len(cards),
        )
        proposal = await self._reviewer.review(review_input)
        if not isinstance(proposal, RuleCandidateHint):
            return None
        if proposal.target_ref != detector_id or not set(proposal.evidence_refs).issubset(
            evidence_refs
        ):
            return None
        return proposal

    async def _card(
        self,
        record: CaseHistoryRevisionRecord,
        *,
        metric: str,
    ) -> dict[str, object] | None:
        if record.storage_ref is None:
            return None
        content = await self._artifacts.get(record.storage_ref)
        if content is None or hashlib.sha256(content).hexdigest() != record.manifest_digest:
            return None
        try:
            document = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(document, dict):
            return None
        if (
            document.get("case_id") != record.case_id
            or document.get("revision") != record.revision
            or document.get("correlation_id") != record.correlation_id
            or document.get("purpose") != record.purpose
            or document.get("access_scope_digest") != record.access_scope_digest
            or document.get("parent_manifest_digest") != record.parent_manifest_digest
        ):
            return None
        sources = document.get("sources")
        bounded_sources = sources[:4] if isinstance(sources, list) else []
        return {
            "case_id": record.case_id,
            "revision": record.revision,
            "manifest_digest": record.manifest_digest,
            "cohort": "failure" if record.outcome_label in _FAILURE_LABELS else "control",
            "outcome_label": record.outcome_label,
            "detector_version": record.detector_version,
            "metric": metric,
            "sources": bounded_sources,
            "evidence_ref": _evidence_ref(record),
        }


def _required(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"case history index field {key!r} MUST be non-empty")
    return item


def _evidence_ref(record: CaseHistoryRevisionRecord) -> str:
    return f"case-history:{record.case_id}:{record.revision}:{record.manifest_digest}"


__all__ = ["CaseHistoryAnalyzer", "CaseHistoryReviewer"]
