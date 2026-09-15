"""Render content-free assignment notices from durable Operator proposals."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.assignment_transport import (
    AssignmentRequestNotice,
    assignment_content_digest,
)


def assignment_notice_from_record(record: Mapping[str, Any]) -> AssignmentRequestNotice:
    """Validate one stored request before transport; never copy role claims onto the bus."""
    fields = ("family", "operation", "principal_id", "idempotency_key", "payload")
    request = {key: record.get(key) for key in fields}
    key = request["idempotency_key"]
    if not isinstance(key, str) or not key.strip() or len(key) > 256:
        raise ValueError("assignment proposal idempotency key is invalid")
    digest = assignment_content_digest(request)
    if (
        record.get("kind") != "operator.proposal"
        or request["family"] != "iam"
        or record.get("mode") != "shadow"
        or record.get("request_digest") != digest
        or record.get("proposal_id") != f"operator-{digest[:32]}"
    ):
        raise ValueError("assignment proposal does not match its durable identity")
    payload = request["payload"]
    if not isinstance(payload, Mapping):
        raise ValueError("assignment proposal payload is invalid")
    return AssignmentRequestNotice.model_validate(
        {
            "schema_version": "1.2.0" if payload.get("case_kind") == "scoped_duty" else "1.1.0",
            "proposal_ref": "operator-proposal:iam:" + hashlib.sha256(key.encode()).hexdigest(),
            "proposal_id": record["proposal_id"],
            "case_id": (
                record["proposal_id"]
                if record["operation"] == "assignments.create"
                else payload.get("case_id")
            ),
            "proposal_digest": digest,
            "operation": record["operation"],
            "accepted_at": record["accepted_at"],
        }
    )


__all__ = ["assignment_notice_from_record"]
