"""Validation of Var's durable final-approval outbox records."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from fdai.agents._framework.var_decisions import final_approval_record
from fdai.agents._framework.var_ticket_identity import approval_action_identity


def validate_final_approval(
    stored: Mapping[str, Any],
    correlation_id: str,
) -> dict[str, Any]:
    approval = dict(stored)
    if (
        approval.get("producer_principal") != "Var"
        or approval.get("correlation_id") != correlation_id
        or approval.get("state") not in {"approved", "rejected"}
        or not isinstance(approval.get("idempotency_key"), str)
        or not approval["idempotency_key"]
        or not _valid_optional_quorum(approval.get("original_quorum_required"))
        or not _valid_optional_quorum(approval.get("effective_quorum_required"))
        or approval.get("development_authority") is not None
        and not isinstance(approval.get("development_authority"), Mapping)
    ):
        raise RuntimeError("stored final approval is malformed")
    approval_action_identity(approval)
    return deepcopy(approval)


def validate_final_record(
    stored: Mapping[str, Any],
    correlation_id: str,
) -> tuple[dict[str, Any], bool]:
    revision = stored.get("revision")
    status = stored.get("publication_status")
    approval_raw = stored.get("approval")
    if (
        stored.get("schema_version") != "1.0.0"
        or stored.get("record_kind") != "final_approval"
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
        or status not in {"pending", "published"}
        or not isinstance(approval_raw, Mapping)
        or stored.get("correlation_id") != correlation_id
    ):
        raise RuntimeError("stored final approval record is malformed")
    approval = validate_final_approval(approval_raw, correlation_id)
    canonical = final_approval_record(
        approval,
        publication_status=str(status),
        revision=revision,
    )
    if dict(stored) != canonical:
        raise RuntimeError("stored final approval record is malformed")
    return approval, status == "published"


def _valid_optional_quorum(value: object) -> bool:
    return value is None or type(value) is int and value >= 1


__all__ = ["validate_final_approval", "validate_final_record"]
