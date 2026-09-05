"""Restart-safe effects for authenticated stewardship merge evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai_service_contracts.handover import StewardshipMergeRecord
from pydantic import ValidationError

from fdai.core.human_assignment import (
    AssignmentOwnershipCoordinator,
    VerifiedOwnershipMerge,
)
from fdai.core.stewardship import (
    StewardshipChangeEvent,
    StewardshipChangePhase,
    StewardshipMap,
    affected_agents_from_stewardship_change,
    build_change_notification,
)
from fdai.core.stewardship.governance import (
    StewardshipGovernanceError,
    validate_stewardship_candidate,
)
from fdai.shared.providers.notifications import NotificationMessage
from fdai.shared.providers.state_store import StateStore

_MERGE_PREFIX = "stewardship_merge:"
_RECEIPT_PREFIX = "stewardship_merge_effect:"
_FAILURE_PREFIX = "stewardship_merge_effect_failure:"
_PROPOSAL_PREFIX = "human_assignment:ownership-proposal:"
_LOGGER = logging.getLogger("fdai.stewardship.merge_effects")


class NotificationDispatcher(Protocol):
    async def dispatch(self, message: NotificationMessage) -> Any: ...


@dataclass(frozen=True, slots=True)
class StewardshipMergeEffectsWorker:
    """Validate merges, notify affected stewards, and advance matching cases."""

    store: StateStore
    base: StewardshipMap
    notifications: NotificationDispatcher
    ownership: AssignmentOwnershipCoordinator | None = None
    validation_environ: Mapping[str, str] | None = None
    interval_seconds: float = 60.0
    batch_limit: int = 100

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("stewardship merge-effects interval MUST be positive")
        if not 1 <= self.batch_limit <= 1000:
            raise ValueError("stewardship merge-effects batch limit MUST be between 1 and 1000")

    async def run_once(self) -> int:
        processed = 0
        offset = 0
        snapshot_total: int | None = None
        while processed < self.batch_limit:
            records, total = await self.store.read_state_page(
                _MERGE_PREFIX,
                limit=self.batch_limit,
                offset=offset,
            )
            if snapshot_total is None:
                snapshot_total = total
            if not records:
                break
            for raw in records:
                processed += int(await self._process(raw))
                if processed >= self.batch_limit:
                    break
            offset += len(records)
            if offset >= snapshot_total:
                break
        return processed

    async def _process(self, raw: Mapping[str, Any]) -> bool:
        failure_key = _failure_key(raw)
        if await self.store.read_state(failure_key) is not None:
            return False
        try:
            merge = StewardshipMergeRecord.model_validate(raw)
        except ValidationError:
            return await self._record_failure(failure_key, "invalid_merge_record", None)
        receipt_key = f"{_RECEIPT_PREFIX}{merge.delivery_id}"
        if await self.store.read_state(receipt_key) is not None:
            return False
        try:
            after = validate_stewardship_candidate(
                merge.merged_yaml,
                environ=self.validation_environ or {},
            )
        except StewardshipGovernanceError:
            return await self._record_failure(
                failure_key,
                "invalid_merged_stewardship",
                merge.delivery_id,
            )

        affected_agents = tuple(sorted(affected_agents_from_stewardship_change(self.base, after)))
        event = StewardshipChangeEvent(
            actor_oid=merge.actor_identity,
            artifact="config/agent-stewardship.yaml",
            affected_agents=affected_agents,
            summary=f"Verified merge commit {merge.merge_commit_sha}.",
            correlation_id=merge.delivery_id,
            phase=StewardshipChangePhase.MERGED,
        )
        message, recipients = build_change_notification(after, event)
        routing = await self.notifications.dispatch(message)
        try:
            assignment_case_id = await self._advance_matching_assignment(merge)
        except ValueError:
            return await self._record_failure(
                failure_key,
                "assignment_merge_mismatch",
                merge.delivery_id,
            )
        recorded_at = datetime.now(UTC).isoformat()
        state = {
            "delivery_id": merge.delivery_id,
            "pr_ref": merge.pr_ref,
            "merge_commit_sha": merge.merge_commit_sha,
            "affected_agents": list(affected_agents),
            "recipient_count": len(recipients),
            "notification_outcome": str(routing.outcome.value),
            "assignment_case_id": assignment_case_id,
            "recorded_at": recorded_at,
        }
        return await self.store.write_state_with_audit_if_absent(
            receipt_key,
            state,
            {
                "actor": "Saga",
                "action_kind": "stewardship.verified_merge_effects",
                **state,
            },
        )

    async def _advance_matching_assignment(
        self,
        merge: StewardshipMergeRecord,
    ) -> str | None:
        if self.ownership is None:
            return None
        proposal = await self.store.find_state(
            _PROPOSAL_PREFIX,
            field="pr_ref",
            value=merge.pr_ref,
        )
        if proposal is None:
            return None
        case_id = proposal.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("matching ownership proposal has no case_id")
        assignment = await self.ownership.cases.get_case(case_id)
        await self.ownership.record_verified_merge(
            case_id=case_id,
            expected_revision=assignment.revision,
            actor_ref=merge.actor_identity,
            merge=VerifiedOwnershipMerge(
                pr_ref=merge.pr_ref,
                merge_commit_sha=merge.merge_commit_sha,
                merged_yaml=merge.merged_yaml,
                merged_at=datetime.now(UTC),
            ),
        )
        return case_id

    async def _record_failure(
        self,
        failure_key: str,
        failure_kind: str,
        delivery_id: str | None,
    ) -> bool:
        recorded_at = datetime.now(UTC).isoformat()
        return await self.store.write_state_with_audit_if_absent(
            failure_key,
            {
                "failure_kind": failure_kind,
                "delivery_id": delivery_id,
                "recorded_at": recorded_at,
            },
            {
                "actor": "Saga",
                "action_kind": "stewardship.verified_merge_rejected",
                "failure_kind": failure_kind,
                "delivery_id": delivery_id,
                "recorded_at": recorded_at,
            },
        )

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                processed = await self.run_once()
                _LOGGER.info(
                    "stewardship_merge_effects_reconciled",
                    extra={"processed": processed},
                )
            except Exception:  # noqa: BLE001 - retry durable evidence after the interval
                _LOGGER.exception("stewardship_merge_effects_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue


def _failure_key(raw: Mapping[str, Any]) -> str:
    serialized = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    return f"{_FAILURE_PREFIX}{hashlib.sha256(serialized.encode()).hexdigest()}"


__all__ = ["NotificationDispatcher", "StewardshipMergeEffectsWorker"]
