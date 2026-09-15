"""Var-owned parking and current readback of existing independent human HIL decisions.

The Operator-owned decision records are the only human source. This service
never writes a decision, dispatches an Action, changes a case or refreshes an
original review window. Role and source readers are injected read-only ports.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai_service_contracts.human_access_execution import (
    HumanAccessApprovalObservation,
    HumanAccessExecutionMaterial,
    canonical_human_access_json,
    human_access_record_digest,
    require_human_access_time,
)

from fdai.shared.providers.state_store import StateStore


class CurrentHumanAccessOwner(Protocol):
    """Resolve exact current active Owner identity, without mutating its role or membership."""

    async def is_current_owner(self, subject_ref: str, *, at: datetime) -> bool:
        """Return current observed eligibility; unavailable or stale evidence cannot authorize."""
        ...


@dataclass(frozen=True, slots=True)
class HumanAccessApprovalService:
    """Park separate slots for the original Action and reread exact current human receipts."""

    store: StateStore
    owners: CurrentHumanAccessOwner
    check_source: Callable[[HumanAccessExecutionMaterial], Awaitable[None]]
    clock: Callable[[], datetime]
    can_approve: Callable[[str, str], bool] | None = None

    async def park(self, material: HumanAccessExecutionMaterial) -> tuple[str, ...]:
        """Create existing HIL queue records with fixed expiry; retries cannot renew or rebind."""
        await self._current(material)
        action = material.action()
        for approval_id in material.approval_ids:
            record = {
                "status": "pending",
                "revision": 0,
                "approval_id": approval_id,
                "idempotency_key": f"human-access:{approval_id}",
                "submitter_oid": material.requester_ref,
                "action": action.model_dump(mode="json"),
                "action_hash": material.action_digest,
                "request_fingerprint": material.digest,
                "action_type": action.action_type,
                "rule_id": action.citing_rules[0],
                "severity": "high",
                "category": "config_drift",
                "correlation_id": str(action.event_id),
                "parked_at": material.recorded_at.isoformat(),
                "approval_context": {
                    "reasons": ["human_access_exact_current_review"],
                    "blast_radius_summary": "one allowlisted person/group membership",
                    "ttl_seconds": 300,
                    "expires_at": material.expires_at.isoformat(),
                },
                "metadata": {
                    "decision_route": "human_access",
                    "required_role": "Owner",
                    "material_digest": material.digest,
                    "action_id": str(action.action_id),
                    "target_subject_ref": material.subject_id,
                },
            }
            key = "hil_park:" + approval_id
            if not await self.store.write_state_with_audit_if_absent(
                key,
                record,
                {
                    "actor": "Var",
                    "action_kind": "human_access.hil.requested",
                    "approval_id": approval_id,
                    "material_digest": material.digest,
                    "action_digest": material.action_digest,
                    "idempotency_key": record["idempotency_key"],
                    "mode": action.mode.value,
                },
            ):
                existing = await self.store.read_state(key)
                if existing is None or _immutable_park(existing) != _immutable_park(record):
                    raise ValueError("human access HIL slot already binds different material")
        await self._current(material)
        return material.approval_ids

    async def read_approvals(
        self, material: HumanAccessExecutionMaterial
    ) -> tuple[HumanAccessApprovalObservation, ...]:
        """Require current independent human slots, excluding stale roles and self-approval."""
        await self._current(material)
        receipts = []
        people = set()
        for approval_id in material.approval_ids:
            park = await self.store.read_state("hil_park:" + approval_id)
            receipt = await self.store.read_state("operator-hil-decision:" + approval_id)
            if park is None or receipt is None:
                raise ValueError("human access independent human quorum is not complete")
            metadata = park.get("metadata")
            context = park.get("approval_context")
            if (
                not isinstance(metadata, Mapping)
                or not isinstance(context, Mapping)
                or metadata.get("decision_route") != "human_access"
                or metadata.get("required_role") != "Owner"
                or metadata.get("material_digest") != material.digest
                or metadata.get("target_subject_ref") != material.subject_id
                or park.get("request_fingerprint") != material.digest
                or park.get("submitter_oid") != material.requester_ref
                or canonical_human_access_json(park.get("action")) != material.action_json
                or context.get("expires_at") != material.expires_at.isoformat()
            ):
                raise ValueError("human access approval context changed from the retained material")
            approver, decided_raw = receipt.get("approver_oid"), receipt.get("decided_at")
            if (
                receipt.get("approval_id") != approval_id
                or receipt.get("idempotency_key") != f"human-access:{approval_id}"
                or receipt.get("decision") != "approve"
                or not isinstance(approver, str)
                or approver != approver.casefold()
                or approver in people
                or approver in {material.requester_ref, material.subject_id}
                or not isinstance(decided_raw, str)
            ):
                raise ValueError(
                    "human access original human decision is absent, rejected or not independent"
                )
            decided = require_human_access_time(datetime.fromisoformat(decided_raw))
            at = require_human_access_time(self.clock())
            if not material.recorded_at <= decided <= at < material.expires_at:
                raise ValueError(
                    "human access human decision is outside the original review window"
                )
            async with asyncio.timeout(5):
                owner = await self.owners.is_current_owner(approver, at=at)
            if owner is not True:
                raise PermissionError("human access reviewer is not a current Owner")
            if (
                self.can_approve is None
                or self.can_approve(approver, material.action().action_type) is not True
            ):
                raise PermissionError(
                    "human access reviewer is not allowed by the current ActionType approval policy"
                )
            people.add(approver)
            receipts.append(
                HumanAccessApprovalObservation(
                    approval_id=approval_id,
                    approver_ref=approver,
                    action_digest=material.action_digest,
                    material_digest=material.digest,
                    decision="approve",
                    decided_at=decided,
                    expires_at=material.expires_at,
                    source_record_digest=human_access_record_digest(
                        {
                            key: receipt[key]
                            for key in (
                                "approval_id",
                                "idempotency_key",
                                "decision",
                                "approver_oid",
                                "decided_at",
                                "receipt_ref",
                            )
                        }
                    ),
                )
            )
        await self._current(material)
        return tuple(receipts)

    async def _current(self, material: HumanAccessExecutionMaterial) -> None:
        at = require_human_access_time(self.clock())
        if not material.recorded_at <= at < material.expires_at:
            raise ValueError("human access original review window expired")
        async with asyncio.timeout(10):
            await self.check_source(material)
            requester = await self.owners.is_current_owner(material.requester_ref, at=at)
        after = require_human_access_time(self.clock())
        if requester is not True or after < at or after >= material.expires_at:
            raise PermissionError("human access current requester or source window is unavailable")


def _immutable_park(value: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value.get(key)
        for key in (
            "approval_id",
            "idempotency_key",
            "submitter_oid",
            "action",
            "action_hash",
            "request_fingerprint",
            "action_type",
            "approval_context",
            "metadata",
        )
    }


__all__ = ["CurrentHumanAccessOwner", "HumanAccessApprovalService"]
