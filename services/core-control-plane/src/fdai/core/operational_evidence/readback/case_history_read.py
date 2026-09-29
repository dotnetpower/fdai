"""Readback for the ``case-history-read`` purpose."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operational_evidence import OperationalEvidenceRejectionClass
from fdai_service_contracts.operator_authentication import (
    OperatorAuthenticationEvidenceClass,
    OperatorAuthenticationReceipt,
)
from pydantic import ValidationError

from ..rejections import ReadbackRejection, reject
from .base import ReadbackContext, ReadbackFacts

_R = OperationalEvidenceRejectionClass
PURPOSE = "case-history-read"
AUTHENTICATION_SOURCE = "operator-service.authentication-receipts"
GRANT_SOURCE = "deployment.case-scope-grants"


@dataclass(frozen=True, slots=True)
class SemanticAuthenticationReceiptRow:
    """One retained Operator authentication receipt row read by exact digest."""

    receipt_digest: str
    request_id: str
    principal_id: str
    receipt: Mapping[str, Any]
    recorded_at: datetime


class SemanticAuthenticationReceiptSource(Protocol):
    """Read retained authentication receipts through a fixed exact-key source."""

    async def receipts_for_request(
        self, receipt_digest: str, request_id: str
    ) -> tuple[SemanticAuthenticationReceiptRow, ...]: ...


class CaseHistoryReadback:
    """Authorize one inert Pattern read from a retained receipt and grant registry."""

    purposes = frozenset({PURPOSE})

    def __init__(self, *, receipts: SemanticAuthenticationReceiptSource) -> None:
        self._receipts = receipts

    async def read(self, context: ReadbackContext) -> ReadbackFacts | ReadbackRejection:
        receipt_ref = context.request.locator.coordinate("authentication_receipt_ref")
        principal_ref = context.request.locator.coordinate("principal_ref")
        case_scope = context.request.locator.coordinate("case_scope_digest").removeprefix("sha256:")
        purpose = context.request.locator.coordinate("purpose")
        principal_groups_digest = context.request.locator.coordinate("principal_groups_digest")
        if purpose != "operations-review":
            return reject(_R.CROSS_SCOPE, "purpose_mismatch")
        request_ref = context.request.locator.coordinate("request_ref")
        rows = await self._receipts.receipts_for_request(receipt_ref, request_ref)
        if not rows:
            return reject(_R.PARTIAL, "authentication_receipt_missing")
        if len(rows) > 1:
            return reject(_R.CONFLICTING, "duplicate_authentication_receipt")
        row = rows[0]
        if row.request_id != request_ref:
            return reject(_R.REPLAY_SUBSTITUTED, "authentication_receipt_request_mismatch")
        try:
            receipt = OperatorAuthenticationReceipt.model_validate(row.receipt)
        except (ValidationError, ValueError):
            return reject(_R.PARTIAL, "authentication_receipt_invalid")
        if receipt.receipt_digest != receipt_ref or row.receipt_digest != receipt_ref:
            return reject(_R.REPLAY_SUBSTITUTED, "authentication_receipt_digest_mismatch")
        if receipt.subject_id != principal_ref or row.principal_id != principal_ref:
            return reject(_R.CROSS_SCOPE, "principal_mismatch")
        if principal_groups_digest != content_digest(list(receipt.groups)):
            return reject(_R.CROSS_SCOPE, "principal_groups_mismatch")
        if not receipt.valid_at(context.read_at):
            return reject(_R.STALE, "authentication_receipt_not_current")
        if (
            context.venue.value == "deployed"
            and receipt.evidence_class is OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK
        ):
            return reject(_R.SYNTHETIC_LIVE, "local_loopback_receipt")
        decision = context.grants.authorize(
            receipt,
            access_scope_digest=case_scope,
            operation="case-history.read",
            purpose_id=PURPOSE,
            at=context.read_at,
        )
        if not decision.allowed or decision.rejection_class is not None:
            return reject(
                decision.rejection_class or _R.CROSS_SCOPE,
                *decision.reasons,
                conflicts=decision.conflicts,
            )
        scope = decision.case_scope
        if scope is None or PURPOSE not in scope.purposes:
            return reject(_R.CROSS_SCOPE, "case_scope_purpose_mismatch")
        auth_anchor = next(
            (
                item.anchor_id
                for item in context.trust.sources
                if item.source_id == AUTHENTICATION_SOURCE
            ),
            "unbound",
        )
        grant_anchor = next(
            (item.anchor_id for item in context.trust.sources if item.source_id == GRANT_SOURCE),
            "unbound",
        )
        return ReadbackFacts(
            evidence_digest=context.request.lookup.evidence_digest,
            source_identity=AUTHENTICATION_SOURCE,
            authentication={
                "authentication_receipt": receipt.receipt_digest,
                "request_id": row.request_id,
                "source_record": row.receipt_digest,
                "writer_anchor": auth_anchor,
            },
            completeness={
                "case_scope": scope.case_scope_id,
                "grant_registry_pin": context.grants.pin,
                "grant_revision": context.grants.revision,
                "known_case_scope": True,
            },
            conflict={
                "duplicate_receipts": 0,
                "principal_groups_match": True,
                "grant_anchor": grant_anchor,
            },
            provenance={
                "source_records": [row.receipt_digest],
                "source_revisions": [context.grants.pin],
            },
            event_at=row.recorded_at,
            evidence_cutoff=context.read_at,
            valid_until_cap=receipt.expires_at,
            matched_grants=decision.matched_grants,
            authentication_receipts=(receipt.model_dump(mode="json"),),
        )


__all__ = [
    "AUTHENTICATION_SOURCE",
    "GRANT_SOURCE",
    "PURPOSE",
    "CaseHistoryReadback",
    "SemanticAuthenticationReceiptRow",
    "SemanticAuthenticationReceiptSource",
]
