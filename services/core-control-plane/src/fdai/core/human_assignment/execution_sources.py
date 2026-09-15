"""Current read-only case/promotion checks and bounded identity evidence for isolated dispatch."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from fdai_service_contracts.human_access_execution import (
    HumanAccessCurrentEvidence,
    HumanAccessExecutionMaterial,
    human_access_record_digest,
    require_human_access_time,
)

from fdai.core.human_assignment.access_planning import HumanAccessPlanner
from fdai.core.human_assignment.execution_approval import HumanAccessApprovalService
from fdai.core.human_assignment.replacement import ReplacementCoveragePlanner
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.rbac.roles import Role
from fdai.shared.contracts.models import Mode

CURRENT_PREFIX = "human_assignment:execution-current:"


class CurrentHumanAccessPromotion(Protocol):
    """Read current verified promotion state; this port never writes or upgrades promotion."""

    async def refresh(self, action_type: str) -> None:
        """Recheck persisted attribution; missing or unavailable evidence clears enforce."""
        ...

    def mode_of(self, action_type: str) -> Mode:
        """Return only the effective mode from the verified current record."""
        ...


@dataclass(frozen=True, slots=True)
class HumanAccessCaseSource:
    """Validate original or exactly prepared case, replacement and promotion on every read."""

    cases: AssignmentCaseService
    role_group_ids: Mapping[Role, str]
    promotions: CurrentHumanAccessPromotion
    clock: Callable[[], datetime]
    check_inverse: Callable[[HumanAccessExecutionMaterial], Awaitable[None]] | None = None

    async def check(self, material: HumanAccessExecutionMaterial) -> None:
        """No case review, display state or stale promotion can replace original source identity."""
        async with asyncio.timeout(10):
            at = require_human_access_time(self.clock())
            if not material.recorded_at <= at < material.expires_at:
                raise ValueError("human access material source window expired")
            action = material.action()
            case = await self.cases.get_case(action.params["case_id"])
            preparation = (
                case.iam_recovery_preparation
                if material.inverse is not None
                else case.iam_preparation
            )
            if preparation is None:
                if (
                    case.revision != action.params["expected_revision"]
                    or human_access_record_digest(case.to_dict()) != material.case_record_digest
                ):
                    raise ValueError("human access original case evidence changed")
            else:
                if (
                    preparation.material_digest != material.digest
                    or preparation.source_case_digest != material.case_record_digest
                    or preparation.source_revision != action.params["expected_revision"]
                    or case.revision != preparation.prepared_revision
                    or case.state.value
                    != ("degraded" if material.inverse is not None else "iam_applying")
                ):
                    raise ValueError("human access prepared case evidence changed")
                original_case = case.to_dict()
                original_case.pop(
                    "iam_recovery_preparation"
                    if material.inverse is not None
                    else "iam_preparation"
                )
                original_case.update(
                    revision=preparation.source_revision,
                    state="degraded"
                    if material.inverse is not None
                    else "approved"
                    if case.intent.revocation is not None
                    else "ownership_merged",
                )
                if human_access_record_digest(original_case) != material.case_record_digest:
                    raise ValueError(
                        "human access prepared case changed outside the exact transition"
                    )
            groups = dict(self.role_group_ids)
            if (
                human_access_record_digest({role.value: group for role, group in groups.items()})
                != material.role_groups_digest
            ):
                raise ValueError("human access role-group source changed")
            if material.inverse is not None:
                if self.check_inverse is None:
                    raise ValueError("human access inverse current evidence source is unavailable")
                await self.check_inverse(material)
                plan = material.membership_plan()
            elif action.action_type == "ops.revoke-human-access":
                planned = await ReplacementCoveragePlanner(self.cases, groups).plan_revocation(
                    case_id=case.case_id, expected_revision=case.revision
                )
                plan = planned.removal
                if action.params["replacement_revisions"] != dict(planned.replacement_revisions):
                    raise ValueError("human access replacement evidence changed")
            else:
                plan = await HumanAccessPlanner(self.cases, groups).plan(
                    case_id=case.case_id, expected_revision=case.revision
                )
            if plan.target_digest != material.membership_plan().target_digest:
                raise ValueError("human access membership target changed")
            await self.promotions.refresh(action.action_type)
            promotion = await self.cases.store.read_state("action_promotion:" + action.action_type)
            if (
                promotion is None
                or self.promotions.mode_of(action.action_type).value != action.mode.value
                or human_access_record_digest(dict(promotion)) != material.promotion_record_digest
            ):
                raise ValueError("human access verified promotion changed or is unavailable")
            current = await self.cases.get_case(case.case_id)
            after = require_human_access_time(self.clock())
            if current != case or after < at or after >= material.expires_at:
                raise ValueError("human access source changed during readback")


@dataclass(frozen=True, slots=True)
class HumanAccessCurrentPublisher:
    """Publish an expiring read projection after Var and current-source checks; never authorize."""

    source: HumanAccessCaseSource
    approvals: HumanAccessApprovalService
    clock: Callable[[], datetime]

    async def observe(self, material: HumanAccessExecutionMaterial) -> HumanAccessCurrentEvidence:
        """Retain at most30seconds of original identity observation, with no sliding read expiry."""
        start = require_human_access_time(self.clock())
        async with asyncio.timeout(25):
            receipts = await self.approvals.read_approvals(material)
            await self.source.check(material)
            case = await self.source.cases.get_case(material.action().params["case_id"])
        binding = (
            case.iam_recovery_preparation if material.inverse is not None else case.iam_preparation
        )
        if binding is None:
            raise ValueError("human access current observation requires exact Core preparation")
        record = HumanAccessCurrentEvidence.model_validate(
            {
                "material_digest": material.digest,
                "prepared_from_case_digest": binding.source_case_digest,
                "prepared_from_revision": binding.source_revision,
                "current_case_revision": case.revision,
                "current_case_state": case.state.value,
                "preparation_ref": binding.reference,
                "role_groups_digest": material.role_groups_digest,
                "promotion_record_digest": material.promotion_record_digest,
                "promotion_mode": material.action().mode.value,
                "approvals": receipts,
                "current_owner_refs": tuple(
                    sorted({material.requester_ref, *(r.approver_ref for r in receipts)})
                ),
                "observed_at": start,
                "expires_at": min(start + timedelta(seconds=30), material.expires_at),
            }
        )
        reason = record.refusal(material, now=self.clock())
        if reason is not None:
            raise ValueError(reason)
        store = self.source.cases.store
        key = CURRENT_PREFIX + material.digest
        prior = await store.read_state(key)
        revision = 1 if prior is None else prior.get("revision", 0) + 1
        value = {"revision": revision, "evidence": record.model_dump(mode="json")}
        audit = {
            "actor": "Var",
            "action_kind": "human_access.current_sources.observed",
            "material_digest": material.digest,
            "revision": revision,
            "mode": "shadow",
        }
        if prior is None:
            persisted = await store.write_state_with_audit_if_absent(key, value, audit)
        else:
            persisted = await store.compare_and_set_state_with_audit(
                key, value, expected_revision=revision - 1, audit_entry=audit
            )
        if not persisted:
            raise ValueError("human access current source observation changed concurrently")
        return record


__all__ = [
    "CURRENT_PREFIX",
    "CurrentHumanAccessPromotion",
    "HumanAccessCaseSource",
    "HumanAccessCurrentPublisher",
]
