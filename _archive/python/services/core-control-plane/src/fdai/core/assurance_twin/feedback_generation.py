"""Reviewed scalar generation replacement using existing StateStore transactions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from fdai.core.assurance_twin.feedback_rebuild import FeedbackRebuildCandidate
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    assess_decision_evidence_admission,
)

REBUILD_PURPOSE = "effect-model-rebuild"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class FeedbackRevisionSource(Protocol):
    """Verify complete immutable revision chains and their latest source heads."""

    async def current(self, revision_digests: tuple[str, ...]) -> bool: ...


def generation_scope(action_type: str, metric: str) -> str:
    from fdai_service_contracts.ontology_query import content_digest

    return content_digest({"action_type": action_type, "metric": metric})


def rebuild_admission_valid(
    admission: DecisionEvidenceAdmission,
    *,
    manifest: str,
    action_type: str,
    metric: str,
    evaluated_at: datetime,
) -> bool:
    return evaluated_at < admission.valid_until and not assess_decision_evidence_admission(
        admission,
        expected_evidence_digest="sha256:" + manifest,
        expected_scope_digest=generation_scope(action_type, metric),
        expected_purpose_id=REBUILD_PURPOSE,
        expected_source_revision=manifest,
        evaluated_at=evaluated_at,
    )


def generation_evidence(
    candidate: FeedbackRebuildCandidate,
    outcomes: tuple[ResponseOutcome, ...],
    admission: DecisionEvidenceAdmission,
) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "input_manifest_digest": candidate.input_manifest_digest,
        "source_digests": list(candidate.source_digests),
        "covered_outcome_ids": sorted(
            {str(item.outcome_id) for item in outcomes if item.recorded_at <= candidate.as_of}
        ),
        "covered_independence_keys": sorted(
            {
                item.prediction_snapshot.independence_key
                for item in outcomes
                if item.prediction_snapshot is not None and item.recorded_at <= candidate.as_of
            }
        ),
        "admission": admission.to_mapping(),
        "replay_order": list(candidate.replay_order),
    }


def read_generation(raw: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = raw.get("generation_evidence")
    if value is None:
        return None
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "schema_version",
            "input_manifest_digest",
            "source_digests",
            "covered_outcome_ids",
            "covered_independence_keys",
            "admission",
            "replay_order",
        }
        or value["schema_version"] != "1.0.0"
        or not isinstance(value["admission"], Mapping)
        or not isinstance(value["input_manifest_digest"], str)
        or _DIGEST.fullmatch(value["input_manifest_digest"]) is None
    ):
        raise ValueError("stored scalar generation evidence is invalid")
    for field in ("source_digests", "covered_outcome_ids", "covered_independence_keys"):
        values = value[field]
        if (
            not isinstance(values, list)
            or len(values) > 1024
            or any(not isinstance(item, str) or not item for item in values)
            or values != sorted(set(values))
        ):
            raise ValueError("stored scalar generation source index is invalid")
        if field != "covered_outcome_ids" and any(
            _DIGEST.fullmatch(item) is None for item in values
        ):
            raise ValueError("stored scalar generation source digest is invalid")
        if field == "covered_outcome_ids":
            for item in values:
                try:
                    canonical = str(UUID(item))
                except ValueError as exc:
                    raise ValueError(
                        "stored scalar generation outcome identity is invalid"
                    ) from exc
                if canonical != item:
                    raise ValueError("stored scalar generation outcome identity is not canonical")
    order = value["replay_order"]
    if (
        not isinstance(order, list)
        or len(order) > 1024
        or any(not isinstance(item, str) for item in order)
        or len(order) != len(set(order))
        or any(item not in value["covered_outcome_ids"] for item in order)
    ):
        raise ValueError("stored scalar generation replay order is invalid")
    return value


def read_admission(raw: Mapping[str, Any]) -> DecisionEvidenceAdmission:
    def timestamp(field: str) -> datetime:
        value = raw.get(field)
        if not isinstance(value, str):
            raise ValueError("stored scalar generation admission time is invalid")
        return datetime.fromisoformat(value)

    def text(field: str) -> str:
        value = raw.get(field)
        if not isinstance(value, str):
            raise ValueError("stored scalar generation admission field is invalid")
        return value

    if raw.get("execution_authority") is not False or raw.get("promotion_authority") is not False:
        raise ValueError("stored scalar generation admission MUST NOT grant authority")
    return DecisionEvidenceAdmission(
        receipt_digest=text("receipt_digest"),
        verification_bundle_digest=text("verification_bundle_digest"),
        evidence_digest=text("evidence_digest"),
        scope_digest=text("scope_digest"),
        purpose_id=text("purpose_id"),
        source_revision=text("source_revision"),
        verified_at=timestamp("verified_at"),
        valid_until=timestamp("valid_until"),
    )
