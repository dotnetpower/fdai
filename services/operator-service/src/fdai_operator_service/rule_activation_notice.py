"""Render content-free Rule activation notices from durable Operator proposals."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.rule_activation import (
    RuleActivationDelta,
    RuleActivationSource,
    rule_activation_proposal_digest,
)
from fdai_service_contracts.rule_activation_transport import RuleActivationRequestNotice

_OPERATIONS = frozenset({"rule.activation-request", "rule.activation-approve"})


def rule_activation_notice_from_record(
    key: str,
    record: Mapping[str, Any],
) -> RuleActivationRequestNotice:
    """Verify one immutable source proposal without copying its body or roles."""

    idempotency_key = record.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError("Rule activation proposal idempotency key is invalid")
    proposal_ref = (
        "operator-proposal:workflow:" + hashlib.sha256(idempotency_key.encode()).hexdigest()
    )
    if key != proposal_ref:
        raise ValueError("Rule activation proposal key does not match its identity")
    request = {
        field: record.get(field)
        for field in ("family", "operation", "principal_id", "idempotency_key", "payload")
    }
    digest = hashlib.sha256(
        json.dumps(request, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    operation = record.get("operation")
    if (
        record.get("kind") != "operator.proposal"
        or record.get("family") != "workflow"
        or operation not in _OPERATIONS
        or record.get("mode") != "shadow"
        or record.get("request_digest") != digest
        or record.get("proposal_id") != f"operator-{digest[:32]}"
    ):
        raise ValueError("Rule activation proposal does not match its durable identity")
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("Rule activation workflow proposal is invalid")
    path_parameters = payload.get("path_parameters")
    if not isinstance(path_parameters, Mapping):
        raise ValueError("Rule activation path parameters are invalid")
    request_id = (
        record["proposal_id"]
        if operation == "rule.activation-request"
        else path_parameters.get("request_id")
    )
    return RuleActivationRequestNotice.model_validate(
        {
            "proposal_ref": proposal_ref,
            "proposal_id": record["proposal_id"],
            "request_id": request_id,
            "proposal_digest": digest,
            "operation": operation,
            "accepted_at": record["accepted_at"],
        }
    )


def rule_activation_proposal_revision(key: str, record: Mapping[str, Any]) -> str:
    """Compute the advisory approval revision that Core independently verifies."""

    notice = rule_activation_notice_from_record(key, record)
    if notice.operation != "rule.activation-request":
        raise ValueError("Only activation requests have an approval revision")
    workflow = record["payload"]
    if not isinstance(workflow, Mapping):
        raise ValueError("Rule activation workflow proposal is invalid")
    body = workflow.get("payload")
    if not isinstance(body, Mapping):
        raise ValueError("Rule activation request body is invalid")
    changes_value = body.get("changes")
    if not isinstance(changes_value, list):
        raise ValueError("Rule activation request changes are invalid")
    changes = tuple(
        sorted(
            (RuleActivationDelta.model_validate(value) for value in changes_value),
            key=lambda change: change.rule_id,
        )
    )
    return rule_activation_proposal_digest(
        idempotency_key=str(record["idempotency_key"]),
        expected_generation_digest=str(workflow.get("expected_revision")),
        source=RuleActivationSource.DIRECT,
        source_ref=notice.proposal_ref,
        source_digest=notice.proposal_digest,
        requested_by=str(record["principal_id"]),
        requested_at=notice.accepted_at,
        reason=str(body.get("reason")),
        changes=changes,
    )


__all__ = ["rule_activation_notice_from_record", "rule_activation_proposal_revision"]
