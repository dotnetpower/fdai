"""Verify immutable Operator assignment receipts before agent review intake."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fdai_service_contracts.assignment_transport import (
    AssignmentIntakeProjection,
    AssignmentIntakeReason,
    AssignmentRequestNotice,
    assignment_content_digest,
)

from fdai.shared.providers.state_store import StateStore

_INTAKE_PREFIX = "human_assignment:intake:"


class AssignmentReceiptReader(Protocol):
    """Read a trusted immutable Operator proposal, never a mutable case projection.

    Implementations must use the Operator-owned durable receipt boundary with its namespace
    write restrictions. A payload or browser-supplied role is not an implementation of this port.
    """

    async def read_state(self, key: str) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class AssignmentRequestIntake:
    """Record an inert, audit-bound intake result without advancing assignment state.

    Saga owns the resulting audit record. Forseti and Var still have to judge and carry
    independent approval. This adapter has no case writer, PR publisher, or IAM provider.
    """

    receipts: AssignmentReceiptReader
    store: StateStore
    maximum_age: timedelta = timedelta(minutes=5)
    clock_skew: timedelta = timedelta(seconds=30)

    def __post_init__(self) -> None:
        if not timedelta(0) < self.maximum_age <= timedelta(minutes=5):
            raise ValueError("assignment receipt maximum age MUST be in (0, 5 minutes]")
        if not timedelta(0) <= self.clock_skew <= timedelta(seconds=30):
            raise ValueError("assignment receipt clock skew MUST be in [0, 30 seconds]")

    async def receive(
        self, notice: AssignmentRequestNotice, *, at: datetime
    ) -> AssignmentIntakeProjection:
        """Resolve the exact source receipt; store failure remains retryable, never success."""
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("assignment receipt clock MUST be timezone-aware")
        at = at.astimezone(UTC)
        key = f"{_INTAKE_PREFIX}{notice.proposal_id}"
        notice_digest = assignment_content_digest(notice.model_dump(mode="json"))
        existing = await self.store.read_state(key)
        if existing is not None:
            if existing.get("notice_digest") != notice_digest:
                raise ValueError("assignment intake notice conflicts with an existing receipt")
            projection = AssignmentIntakeProjection.model_validate(existing.get("projection"))
            if projection.proposal_digest != notice.proposal_digest:
                raise ValueError("assignment intake identity conflicts with an existing receipt")
            return projection
        record = await self.receipts.read_state(notice.proposal_ref)
        reason = self.receipt_reason(notice, record, at=at)
        projection = AssignmentIntakeProjection(
            proposal_id=notice.proposal_id,
            proposal_digest=notice.proposal_digest,
            status="awaiting_agent_review" if reason == "verified_operator_receipt" else "held",
            reason=reason,
            observed_at=at,
        )
        # An unverified notice must not preempt the canonical source's later valid intake.
        # Keep its audit in a notice-specific hold namespace, not the successful receipt key.
        if reason != "verified_operator_receipt":
            await self.store.write_state_with_audit_if_absent(
                f"{key}:held:{notice_digest}",
                {"notice_digest": notice_digest, "projection": projection.model_dump(mode="json")},
                {
                    "actor": "Saga",
                    "action_kind": "human.assignment.request_intake_held",
                    "proposal_id": notice.proposal_id,
                    "reason": reason,
                    "recorded_at": at.isoformat(),
                    "mode": "shadow",
                },
            )
            return projection
        created = await self.store.write_state_with_audit_if_absent(
            key,
            {"notice_digest": notice_digest, "projection": projection.model_dump(mode="json")},
            {
                "actor": "Saga",
                "action_kind": "human.assignment.request_intake_observed",
                "proposal_id": notice.proposal_id,
                "proposal_digest": notice.proposal_digest,
                "status": projection.status,
                "reason": projection.reason,
                "recorded_at": at.isoformat(),
                "mode": "shadow",
            },
        )
        if not created:
            raced = await self.store.read_state(key)
            if raced is None:
                raise RuntimeError("assignment intake receipt disappeared after create race")
            if raced.get("notice_digest") != notice_digest:
                raise ValueError("assignment intake notice conflicts after create race")
            winner = AssignmentIntakeProjection.model_validate(raced.get("projection"))
            if winner.proposal_digest != notice.proposal_digest:
                raise ValueError("assignment intake identity conflicts after create race")
            return winner
        return projection

    def receipt_reason(
        self,
        notice: AssignmentRequestNotice,
        record: Mapping[str, Any] | None,
        *,
        at: datetime,
    ) -> AssignmentIntakeReason:
        """Revalidate current source freshness even when an earlier intake was successful."""
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("assignment receipt clock MUST be timezone-aware")
        if record is None:
            return "operator_receipt_unavailable"
        expected_fields = ("family", "operation", "principal_id", "idempotency_key", "payload")
        request = {key: record.get(key) for key in expected_fields}
        try:
            digest = assignment_content_digest(request)
        except (TypeError, ValueError):
            return "operator_receipt_mismatch"
        idempotency_key = request["idempotency_key"]
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            return "operator_receipt_mismatch"
        source_key = "operator-proposal:iam:" + hashlib.sha256(idempotency_key.encode()).hexdigest()
        if (
            source_key != notice.proposal_ref
            or digest != notice.proposal_digest
            or record.get("request_digest") != digest
            or record.get("proposal_id") != notice.proposal_id
            or record.get("kind") != "operator.proposal"
            or record.get("mode") != "shadow"
            or request["family"] != "iam"
            or request["operation"] != notice.operation
        ):
            return "operator_receipt_mismatch"
        try:
            accepted = datetime.fromisoformat(str(record.get("accepted_at")))
        except ValueError:
            return "operator_receipt_mismatch"
        if (
            accepted.tzinfo is None
            or accepted.utcoffset() is None
            or accepted != notice.accepted_at
        ):
            return "operator_receipt_mismatch"
        age = at - accepted
        if age < -self.clock_skew or age >= self.maximum_age:
            return "operator_receipt_expired"
        payload = request["payload"]
        if not isinstance(payload, Mapping):
            return "operator_receipt_unauthorized"
        source_case = (
            record["proposal_id"]
            if notice.operation == "assignments.create"
            else payload.get("case_id")
        )
        if source_case != notice.case_id:
            return "operator_receipt_mismatch"
        principal = payload.get("principal")
        if not isinstance(principal, Mapping):
            return "operator_receipt_unauthorized"
        oid = principal.get("oid")
        roles = principal.get("roles")
        if (
            not isinstance(oid, str)
            or not oid.strip()
            or oid != request["principal_id"]
            or not isinstance(roles, list)
            or any(
                not isinstance(role, str)
                or role not in {"Reader", "Contributor", "Approver", "Owner"}
                for role in roles
            )
            or "Owner" not in roles
        ):
            return "operator_receipt_unauthorized"
        return "verified_operator_receipt"


__all__ = ["AssignmentReceiptReader", "AssignmentRequestIntake"]
