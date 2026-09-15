"""Vidar recovery evidence and Forseti inverse material without provider mutation or human approval.

Only an acknowledged owned membership can be proposed for restoration. New
human slots review that inverse; original approval and expired dispatch windows
are never reused. Current demand and the shared target generation stay binding.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fdai_service_contracts.human_access_execution import (
    HumanAccessExecutionMaterial,
    canonical_human_access_json,
    human_access_record_digest,
)
from fdai_service_contracts.human_access_recovery import (
    HumanAccessInverseBinding,
    membership_attempt_key,
    mutation_evidence_digest,
    require_inverse_fence,
)

from fdai.core.executor.target_dispatch_fence_codec import target_dispatch_fence_to_mapping
from fdai.core.executor.target_dispatch_fence_store import TargetDispatchFenceStore
from fdai.core.human_assignment.execution_material import HumanAccessMaterialBuilder
from fdai.core.human_assignment.model import AssignmentCase, AssignmentState
from fdai.shared.contracts.models import Action
from fdai.shared.providers.resource_lock import resource_lock_target_digest


@dataclass(frozen=True, slots=True)
class HumanAccessRecoverySource:
    """Bounded exact Executor evidence and demand reads; never write another service's records."""

    builder: HumanAccessMaterialBuilder
    fences: TargetDispatchFenceStore

    async def inspect(self, original: HumanAccessExecutionMaterial) -> dict[str, Any]:
        """Read the original acknowledged attempt and complete current membership demand."""
        async with asyncio.timeout(10):
            if original.inverse is not None:
                raise ValueError("human access recovery cannot recursively invert an inverse")
            action = original.action()
            store = self.builder.cases.store
            prefix = membership_attempt_key(action.idempotency_key)
            intent, result = (
                await store.read_state(prefix + ":intent"),
                await store.read_state(prefix + ":result"),
            )
            if intent is None or result is None:
                raise ValueError("human access original mutation is unacknowledged")
            target = resource_lock_target_digest(action.target_resource_ref)
            fence = await self.fences.read(target)
            if fence is None:
                raise ValueError("human access original target fence is unavailable")
            rows, total = await store.read_state_page(
                "human_assignment:case:", limit=1000, offset=0
            )
            if total != len(rows):
                raise ValueError("human access recovery current demand is incomplete")
            case_id = action.params["case_id"]
            current = await self.builder.cases.get_case(case_id)
            related_ids = {case_id}
            if current.intent.revocation is not None:
                related_ids.add(current.intent.revocation.case_id)
                related_ids.update(current.intent.revocation.replacement_revisions)
            demand = {}
            other_demand = False
            for raw in rows:
                candidate = AssignmentCase.from_dict(dict(raw))
                same = (
                    candidate.intent.subject == current.intent.subject
                    and candidate.intent.requested_role is current.intent.requested_role
                )
                if same or candidate.case_id in related_ids:
                    # Own-case CAS has its own digest; preparation must not alter demand.
                    if candidate.case_id != case_id:
                        demand[candidate.case_id] = candidate.to_dict()
                if (
                    same
                    and candidate.case_id != case_id
                    and candidate.intent.revocation is None
                    and candidate.state
                    in {
                        AssignmentState.ACTIVE,
                        AssignmentState.IAM_APPLYING,
                        AssignmentState.DEGRADED,
                    }
                ):
                    other_demand = True
            return {
                "intent": dict(intent),
                "result": dict(result),
                "fence": target_dispatch_fence_to_mapping(fence),
                "demand_digest": human_access_record_digest(demand),
                "other_demand": other_demand,
            }

    async def binding(self, original: HumanAccessExecutionMaterial) -> HumanAccessInverseBinding:
        """Require a resolved original generation and proven owned pre-state before proposing."""
        snapshot = await self.inspect(original)
        intent, result, fence = snapshot["intent"], snapshot["result"], snapshot["fence"]
        before = intent.get("before_membership")
        if type(before) is not bool or before is original.membership_plan().desired_membership:
            raise ValueError("human access original membership was not changed by this attempt")
        if (
            fence.get("state") != "resolved"
            or fence["identity"].get("sink_idempotency_key") != original.action().idempotency_key
        ):
            raise ValueError(
                "human access recovery requires original authoritative release closure"
            )
        if before is False and snapshot["other_demand"]:
            raise ValueError("human access membership remains required by another assignment")
        binding = HumanAccessInverseBinding(
            original_action_id=original.action().action_id,
            original_action_digest=original.action_digest,
            original_material_digest=original.digest,
            original_idempotency_key=original.action().idempotency_key,
            original_target_digest=original.membership_plan().target_digest,
            original_attempt_digest=mutation_evidence_digest(intent, result),
            original_before_membership=before,
            original_receipt_ref=result["receipt_ref"],
            original_completed_at=result["recorded_at"],
            target_fence_digest=fence["record_digest"],
            target_fence_generation=fence["identity"]["generation"],
            demand_digest=snapshot["demand_digest"],
        )
        binding.require_owned(intent, result)
        return binding

    async def check(self, material: HumanAccessExecutionMaterial) -> None:
        """Revalidate original mutation and unchanged target/demand at each await fence."""
        inverse = material.inverse
        if inverse is None:
            raise ValueError("human access recovery binding is missing")
        original = await self.builder.materials.read(str(inverse.original_action_id))
        if original is None or original.digest != inverse.original_material_digest:
            raise ValueError("human access recovery original material changed")
        snapshot = await self.inspect(original)
        inverse.require_owned(snapshot["intent"], snapshot["result"])
        require_inverse_fence(
            inverse, snapshot["fence"], inverse_key=material.action().idempotency_key
        )
        if snapshot["demand_digest"] != inverse.demand_digest or (
            not inverse.original_before_membership and snapshot["other_demand"]
        ):
            raise ValueError("human access recovery membership demand changed")

    async def build(
        self,
        *,
        action: Action,
        original: HumanAccessExecutionMaterial,
        promotion: Mapping[str, Any],
        at: datetime,
    ) -> HumanAccessExecutionMaterial:
        """Retain a new inverse Action without forging an old review or a new case."""
        prior = await self.builder.materials.read(str(action.action_id))
        if prior is not None:
            if prior.action_json != canonical_human_access_json(action.model_dump(mode="json")):
                raise ValueError("human access recovery Action was rebound")
            return prior
        current = await self.builder.cases.get_case(action.params["case_id"])
        if self.builder.role_group_ids.get(current.intent.requested_role) != original.group_id:
            raise ValueError(
                "human access original recovery group is no longer the current role binding"
            )
        if (
            current.state is not AssignmentState.DEGRADED
            or current.revision != action.params["expected_revision"]
            or current.iam_preparation is None
            or current.iam_preparation.material_digest != original.digest
            or current.iam_recovery_preparation is not None
        ):
            raise ValueError("human access recovery requires the exact held original case")
        binding = await self.binding(original)
        if (
            promotion.get("action_type") != action.action_type
            or promotion.get("mode") != action.mode.value
        ):
            raise ValueError("human access inverse promotion source is inconsistent")
        material = HumanAccessExecutionMaterial(
            action_json=canonical_human_access_json(action.model_dump(mode="json")),
            subject_id=original.subject_id,
            group_id=original.group_id,
            requested_role=original.requested_role,
            requester_ref=original.requester_ref,
            case_record_digest=human_access_record_digest(current.to_dict()),
            role_groups_digest=human_access_record_digest(
                {role.value: group for role, group in self.builder.role_group_ids.items()}
            ),
            promotion_record_digest=human_access_record_digest(dict(promotion)),
            inverse=binding,
            approval_ids=tuple(
                str(uuid5(NAMESPACE_URL, f"fdai:human-access:{action.action_id}:{slot}"))
                for slot in range(original.quorum)
            ),
            recorded_at=at,
            expires_at=at + timedelta(minutes=5),
        )
        if await self.builder.cases.get_case(current.case_id) != current:
            raise ValueError("human access recovery case changed during material construction")
        return await self.builder.materials.retain(material)


__all__ = ["HumanAccessRecoverySource"]
