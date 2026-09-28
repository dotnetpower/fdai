"""Readback for the ``operator-test-context-command`` purpose."""

from __future__ import annotations

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operational_evidence import OperationalEvidenceRejectionClass

from ..rejections import ReadbackRejection, reject
from .base import ReadbackContext, ReadbackFacts
from .test_context_sources import (
    OPERATOR_OUTBOX_SOURCE,
    OperatorCommandSource,
    authenticate_command,
)

_R = OperationalEvidenceRejectionClass
PURPOSE = "operator-test-context-command"


class OperatorTestContextCommandReadback:
    """Re-establish one Operator command from its row, receipt, and explicit grant."""

    purposes = frozenset({PURPOSE})

    def __init__(self, *, commands: OperatorCommandSource) -> None:
        self._commands = commands

    async def read(self, context: ReadbackContext) -> ReadbackFacts | ReadbackRejection:
        key = context.request.locator.coordinate("idempotency_key")
        rows = await self._commands.commands_for_key(key)
        if not rows:
            return reject(_R.PARTIAL, "source_record_missing")
        if len(rows) > 1:
            return reject(
                _R.CONFLICTING,
                "competing_command_record",
                conflicts=(content_digest(row.key) for row in rows),
            )
        authenticated = authenticate_command(
            rows[0],
            grants=context.grants,
            venue=context.venue,
            purpose_id=PURPOSE,
            at=context.read_at,
        )
        if isinstance(authenticated, ReadbackRejection):
            return authenticated
        request = authenticated.command.request
        lookup = context.request.lookup
        if "sha256:" + request.access_scope_digest != lookup.scope_digest:
            return reject(_R.CROSS_SCOPE, "scope_mismatch")
        if request.policy_revision != lookup.source_revision:
            return reject(_R.REPLAY_SUBSTITUTED, "source_revision_mismatch")
        scope = authenticated.decision.case_scope
        row = authenticated.row
        writer_anchor = next(
            (
                item.anchor_id
                for item in context.trust.sources
                if item.source_id == OPERATOR_OUTBOX_SOURCE
            ),
            "unbound",
        )
        return ReadbackFacts(
            evidence_digest=authenticated.digest,
            source_identity=OPERATOR_OUTBOX_SOURCE,
            authentication={
                "authentication_receipt": authenticated.receipt.receipt_digest,
                "source_record": content_digest(row.key),
                "writer_anchor": writer_anchor,
            },
            completeness={
                "case_scope": scope.case_scope_id if scope is not None else None,
                "delivery_state": row.dispatch_status,
                "record_count": 1,
                "request_digest": row.record.get("request_digest"),
            },
            conflict={
                "competing_records": 0,
                "policy_revision": request.policy_revision,
            },
            provenance={
                "source_records": [content_digest(row.key)],
                "source_revisions": [row.record.get("request_digest")],
            },
            event_at=authenticated.command.requested_at,
            evidence_cutoff=authenticated.command.requested_at,
            matched_grants=authenticated.decision.matched_grants,
            authentication_receipts=(authenticated.receipt.model_dump(mode="json"),),
        )


__all__ = ["PURPOSE", "OperatorTestContextCommandReadback"]
