"""Readback for the ``current-case-reuse`` purpose."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast

from fdai_service_contracts.operational_evidence import OperationalEvidenceRejectionClass
from pydantic import ValidationError

from fdai.core.tiers.t1_lightweight.contextual_reuse import (
    CurrentReuseVerification,
    current_reuse_evidence_digest,
)

from ..rejections import ReadbackRejection, reject
from .base import ReadbackContext, ReadbackFacts

_R = OperationalEvidenceRejectionClass
PURPOSE = "current-case-reuse"
INVENTORY_SOURCE = "inventory.current-snapshot"
CASE_HISTORY_SOURCE = "core-control-plane.case-history"
SAFETY_RECEIPT_SOURCE = "core-control-plane.safety-receipts"
_SAFETY_FIELDS = (
    "preconditions_passed",
    "target_identity_verified",
    "blast_radius_within_limit",
    "policy_allowed",
    "dry_run_passed",
    "idempotency_available",
    "rollback_resolved",
)


class CurrentCaseReuseSource(Protocol):
    """Read Muninn's current case, current inventory, and retained safety receipts."""

    async def current_reuse(
        self, *, case_ref: str, resource_ref: str, event_id: str
    ) -> Mapping[str, object] | None: ...


@dataclass(frozen=True, slots=True)
class CurrentCaseReuseReadback:
    """Recompute current reuse digests from readable current sources and safety receipts."""

    source: CurrentCaseReuseSource

    purposes = frozenset({PURPOSE})

    async def read(self, context: ReadbackContext) -> ReadbackFacts | ReadbackRejection:
        locator = context.request.locator
        raw = await self.source.current_reuse(
            case_ref=locator.coordinate("case_ref"),
            resource_ref=locator.coordinate("resource_ref"),
            event_id=locator.coordinate("event_id"),
        )
        if raw is None:
            return reject(_R.PARTIAL, "source_record_missing")
        expected = {
            "verification",
            "case_scope_digest",
            "target_scope_digest",
            "case_revision",
            "inventory_generation",
            "safety_receipts",
            "scope_digest",
        }
        if set(raw) != expected:
            return reject(_R.PARTIAL, "source_record_malformed")
        try:
            verification_values = cast(Any, _verification_mapping(raw["verification"]))
            verification = CurrentReuseVerification(**verification_values)
        except (TypeError, ValueError, ValidationError):
            return reject(_R.PARTIAL, "source_record_malformed")
        safety_receipts = tuple(_strings(raw["safety_receipts"], label="safety_receipts"))
        if len(safety_receipts) != len(_SAFETY_FIELDS):
            return reject(_R.PARTIAL, "safety_receipt_missing")
        if verification.evidence_refs != tuple(sorted(set(verification.evidence_refs))):
            return reject(
                _R.CONFLICTING,
                "receipt_disagreement",
                conflicts=verification.evidence_refs,
            )
        if current_reuse_evidence_digest(verification) != context.request.lookup.evidence_digest:
            return reject(_R.REPLAY_SUBSTITUTED, "evidence_mismatch")
        if raw["scope_digest"] != context.request.lookup.scope_digest:
            return reject(_R.CROSS_SCOPE, "target_scope_mismatch")
        if verification.graph_digest != context.request.lookup.source_revision:
            return reject(_R.REPLAY_SUBSTITUTED, "source_revision_mismatch")
        decision = context.grants.authorize_reuse(
            case_scope_digest=str(raw["case_scope_digest"]).removeprefix("sha256:"),
            target_scope_digest=str(raw["target_scope_digest"]).removeprefix("sha256:"),
            at=context.read_at,
        )
        if not decision.allowed or decision.rejection_class is not None:
            return reject(
                decision.rejection_class or _R.CROSS_SCOPE,
                *decision.reasons,
                conflicts=decision.conflicts,
            )
        if not all(getattr(verification, field) for field in _SAFETY_FIELDS):
            return reject(_R.PARTIAL, "safety_result_failed")
        return ReadbackFacts(
            evidence_digest=context.request.lookup.evidence_digest,
            source_identity=INVENTORY_SOURCE,
            authentication={
                "case_ref": verification.case_ref,
                "case_revision": raw["case_revision"],
                "inventory_generation": raw["inventory_generation"],
            },
            completeness={
                "complete_graph_generation": raw["inventory_generation"],
                "safety_receipts": list(safety_receipts),
                "case_revision": raw["case_revision"],
            },
            conflict={
                "generation_disagreements": 0,
                "case_revision_disagreements": 0,
                "receipt_disagreements": 0,
            },
            provenance={
                "sources": [INVENTORY_SOURCE, CASE_HISTORY_SOURCE, SAFETY_RECEIPT_SOURCE],
                "evidence_refs": list(verification.evidence_refs),
            },
            event_at=verification.observed_at,
            evidence_cutoff=verification.observed_at,
            matched_grants=decision.matched_grants,
        )


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} MUST be an object")
    return value


def _verification_mapping(value: object) -> dict[str, object]:
    raw = dict(_mapping(value, label="verification"))
    observed_at = raw.get("observed_at")
    if isinstance(observed_at, str):
        raw["observed_at"] = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    refs = raw.get("evidence_refs")
    if isinstance(refs, list):
        raw["evidence_refs"] = tuple(refs)
    for field in _SAFETY_FIELDS:
        if type(raw.get(field)) is not bool:
            raise ValueError("current reuse safety result MUST be boolean")
    return raw


def _strings(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} MUST be a string list")
    return tuple(value)


__all__ = [
    "CASE_HISTORY_SOURCE",
    "INVENTORY_SOURCE",
    "PURPOSE",
    "SAFETY_RECEIPT_SOURCE",
    "CurrentCaseReuseReadback",
    "CurrentCaseReuseSource",
]
