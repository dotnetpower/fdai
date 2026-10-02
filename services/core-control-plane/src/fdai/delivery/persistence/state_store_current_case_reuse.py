"""Retained current-case reuse source records for verifier readback."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from fdai.core.tiers.t1_lightweight import (
    CurrentReuseVerification,
    LearnedAction,
    OperationalCaseContext,
)
from fdai.core.tiers.t1_lightweight.contextual_reuse import current_reuse_scope_digest
from fdai.shared.contracts.models import Event
from fdai.shared.providers.state_store import StateStore

CURRENT_CASE_REUSE_PREFIX = "current-case-reuse:v1:"
_SAFETY_FIELDS = (
    "preconditions_passed",
    "target_identity_verified",
    "blast_radius_within_limit",
    "policy_allowed",
    "dry_run_passed",
    "idempotency_available",
    "rollback_resolved",
)


@dataclass(frozen=True, slots=True)
class StateStoreCurrentCaseReuseSource:
    """StateStore-backed source used by tests and local verifier composition."""

    store: StateStore

    async def current_reuse(
        self, *, case_ref: str, resource_ref: str, event_id: str
    ) -> Mapping[str, object] | None:
        return await self.store.read_state(_key(case_ref, resource_ref, event_id))


@dataclass(frozen=True, slots=True)
class StateStoreCurrentCaseReuseRetainer:
    """Retain live current-reuse verifications in the StateStore."""

    store: StateStore

    async def retain(
        self,
        *,
        event: Event,
        action: LearnedAction,
        context: OperationalCaseContext,
        resource_ref: str,
        verification: CurrentReuseVerification,
    ) -> Mapping[str, object]:
        return await retain_current_case_reuse_source(
            self.store,
            event=event,
            action=action,
            context=context,
            resource_ref=resource_ref,
            verification=verification,
        )


async def retain_current_case_reuse_source(
    store: StateStore,
    *,
    event: Event,
    action: LearnedAction,
    context: OperationalCaseContext,
    resource_ref: str,
    verification: CurrentReuseVerification,
) -> Mapping[str, object]:
    """Retain one queryable current-reuse source row before the verifier reads it."""

    scope_digest = current_reuse_scope_digest(event=event, action=action, context=context)
    record: dict[str, object] = {
        "schema_version": "1.0.0",
        "verification": _verification(verification),
        "case_scope_digest": "sha256:" + (context.access_scope_digest or context.graph_digest),
        "target_scope_digest": scope_digest,
        "case_revision": context.case_ref,
        "inventory_generation": verification.graph_digest,
        "safety_receipts": list(_safety_receipts(verification)),
        "scope_digest": scope_digest,
        "case_ref": context.case_ref,
        "resource_ref": resource_ref,
        "event_id": str(event.event_id),
        "recorded_at": verification.observed_at.isoformat(),
    }
    await store.write_state(_key(context.case_ref, resource_ref, str(event.event_id)), record)
    return record


def current_case_reuse_source_key(case_ref: str, resource_ref: str, event_id: str) -> str:
    return _key(case_ref, resource_ref, event_id)


def _key(case_ref: str, resource_ref: str, event_id: str) -> str:
    digest = hashlib.sha256(f"{case_ref}\n{resource_ref}\n{event_id}".encode()).hexdigest()
    return CURRENT_CASE_REUSE_PREFIX + digest


def _verification(verification: CurrentReuseVerification) -> dict[str, object]:
    return {
        "case_ref": verification.case_ref,
        "observed_at": verification.observed_at.isoformat(),
        "evidence_refs": list(verification.evidence_refs),
        "failure_fingerprint": verification.failure_fingerprint,
        "resource_type": verification.resource_type,
        "topology_role": verification.topology_role,
        "graph_digest": verification.graph_digest,
        "owner_digest": verification.owner_digest,
        **{field: bool(getattr(verification, field)) for field in _SAFETY_FIELDS},
    }


def _safety_receipts(verification: CurrentReuseVerification) -> tuple[str, ...]:
    return tuple(
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                {
                    "field": field,
                    "passed": bool(getattr(verification, field)),
                    "evidence_refs": verification.evidence_refs,
                    "observed_at": verification.observed_at.isoformat(),
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        for field in _SAFETY_FIELDS
    )


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp expected")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


__all__ = [
    "CURRENT_CASE_REUSE_PREFIX",
    "StateStoreCurrentCaseReuseRetainer",
    "StateStoreCurrentCaseReuseSource",
    "current_case_reuse_source_key",
    "retain_current_case_reuse_source",
]
