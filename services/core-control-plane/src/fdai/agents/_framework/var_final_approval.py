"""Validation of Var's durable final-approval outbox records."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from fdai.agents._framework.var_decisions import final_approval_record
from fdai.agents._framework.var_ticket_identity import (
    approval_action_identity,
    approval_state_key,
)


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
        or status not in {"pending", "publishing", "published"}
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


async def claim_approval_publication(
    *,
    store: Any | None,
    approval: Mapping[str, Any],
    published_cache: set[tuple[str, str]] | Any,
) -> bool:
    correlation_id = str(approval["correlation_id"])
    action_run_identity = approval_action_identity(approval)
    cache_key = (correlation_id, action_run_identity or "non-action")
    if cache_key in published_cache:
        return False
    if store is None:
        return True
    key = approval_state_key(correlation_id, "final", action_run_identity)
    for _attempt in range(16):
        stored = await store.read_state(key)
        if stored is None:
            raise RuntimeError("approval final record disappeared before publication")
        stored_approval, published = validate_final_record(stored, correlation_id)
        if stored_approval != dict(approval):
            raise RuntimeError("approval publication receipt collision")
        if published:
            published_cache.add(cache_key)
            return False
        if stored.get("publication_status") == "publishing":
            return False
        revision = int(stored["revision"])
        advanced = await store.compare_and_set_state_with_audit(
            key,
            final_approval_record(
                stored_approval,
                publication_status="publishing",
                revision=revision + 1,
            ),
            expected_revision=revision,
            audit_entry={
                "actor": "Var",
                "action_kind": "approval.publish_claimed",
                "correlation_id": correlation_id,
                "idempotency_key": str(approval["idempotency_key"]),
                "state": str(approval["state"]),
            },
        )
        if advanced:
            return True
    raise RuntimeError("approval publication claim CAS retry limit exceeded")


async def release_approval_publication_claim(
    *,
    store: Any | None,
    approval: Mapping[str, Any],
) -> None:
    if store is None:
        return
    correlation_id = str(approval["correlation_id"])
    action_run_identity = approval_action_identity(approval)
    key = approval_state_key(correlation_id, "final", action_run_identity)
    for _attempt in range(16):
        stored = await store.read_state(key)
        if stored is None or stored.get("publication_status") != "publishing":
            return
        stored_approval, _published = validate_final_record(stored, correlation_id)
        if stored_approval != dict(approval):
            raise RuntimeError("approval publication receipt collision")
        revision = int(stored["revision"])
        advanced = await store.compare_and_set_state(
            key,
            final_approval_record(
                stored_approval,
                publication_status="pending",
                revision=revision + 1,
            ),
            expected_revision=revision,
        )
        if advanced:
            return
    raise RuntimeError("approval publication claim release CAS retry limit exceeded")


def _valid_optional_quorum(value: object) -> bool:
    return value is None or type(value) is int and value >= 1


__all__ = [
    "claim_approval_publication",
    "release_approval_publication_claim",
    "validate_final_approval",
    "validate_final_record",
]
