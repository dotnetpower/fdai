"""Retain one pre-review Action and its current private assignment source.

Forseti owns construction/judgment, Var owns independent human approval, and
Muninn owns case preparation after Saga seals it. This builder calls no agent,
provider mutation, promotion writer or HIL decision writer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from fdai_service_contracts.human_access_execution import (
    HUMAN_ACCESS_ACTIONS,
    HumanAccessExecutionMaterial,
    canonical_human_access_json,
    human_access_record_digest,
    require_human_access_time,
)

from fdai.core.human_assignment.access_planning import HumanAccessPlanner
from fdai.core.human_assignment.replacement import ReplacementCoveragePlanner
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.rbac.roles import Role
from fdai.shared.contracts.models import Action
from fdai.shared.providers.state_store import StateStore

MATERIAL_PREFIX = "human_assignment:execution-material:"


@dataclass(frozen=True, slots=True)
class HumanAccessMaterialStore:
    """Immutable Core-owned material; readers resolve exact Action identity, not arbitrary text."""

    store: StateStore

    async def retain(self, material: HumanAccessExecutionMaterial) -> HumanAccessExecutionMaterial:
        """Atomically retain source and audit; a reused Action id cannot bind different bytes."""
        key = MATERIAL_PREFIX + str(material.action().action_id)
        payload = material.model_dump(mode="json")
        created = await self.store.write_state_with_audit_if_absent(
            key,
            payload,
            {
                "actor": "Forseti",
                "action_kind": "human_access.material.retained",
                "material_digest": material.digest,
                "action_digest": material.action_digest,
                "mode": material.action().mode.value,
            },
        )
        if not created and await self.store.read_state(key) != payload:
            raise ValueError("human access Action identity already binds different material")
        return material

    async def read(self, action_id: str) -> HumanAccessExecutionMaterial | None:
        """Read the exact retained material without refreshing its source or deadline."""
        payload = await self.store.read_state(MATERIAL_PREFIX + action_id)
        if payload is None:
            return None
        material = HumanAccessExecutionMaterial.model_validate(payload)
        if str(material.action().action_id) != action_id:
            raise ValueError("human access retained Action identity is inconsistent")
        return material


@dataclass(frozen=True, slots=True)
class HumanAccessMaterialBuilder:
    """Bind an original catalog-built Action to exact current case and role-group evidence."""

    cases: AssignmentCaseService
    materials: HumanAccessMaterialStore
    role_group_ids: Mapping[Role, str]

    async def build(
        self, *, action: Action, promotion_record: Mapping[str, object], at: datetime
    ) -> HumanAccessExecutionMaterial:
        """Never rewrite the Action or infer approval/promotion from its mode.

        The caller must select mode from the existing verified registry before
        construction. This method checks unchanged source identity and retains
        a bounded proposal, not authority to prepare a case or invoke Executor.
        """
        now = require_human_access_time(at)
        if action.action_type not in HUMAN_ACCESS_ACTIONS or action.created_at != now:
            raise ValueError("human access material requires an original current catalog Action")
        case_id, revision = action.params.get("case_id"), action.params.get("expected_revision")
        if not isinstance(case_id, str) or type(revision) is not int:
            raise ValueError("human access material requires exact current case arguments")
        prior = await self.materials.read(str(action.action_id))
        if prior is not None:
            if prior.action_json != canonical_human_access_json(action.model_dump(mode="json")):
                raise ValueError("retained human access Action MUST NOT be rewritten")
            return prior
        async with asyncio.timeout(10):
            case = await self.cases.get_case(case_id)
            before = human_access_record_digest(case.to_dict())
            groups = dict(self.role_group_ids)
            if action.action_type == "ops.revoke-human-access":
                replacement = await ReplacementCoveragePlanner(self.cases, groups).plan_revocation(
                    case_id=case_id, expected_revision=revision
                )
                plan = replacement.removal
                if action.params.get("replacement_revisions") != dict(
                    replacement.replacement_revisions
                ):
                    raise ValueError(
                        "human access replacement revisions differ from reviewed intent"
                    )
            else:
                plan = await HumanAccessPlanner(self.cases, groups).plan(
                    case_id=case_id, expected_revision=revision
                )
            if human_access_record_digest((await self.cases.get_case(case_id)).to_dict()) != before:
                raise ValueError("human access case changed during material construction")
        if (
            promotion_record.get("action_type") != action.action_type
            or promotion_record.get("mode") != action.mode.value
        ):
            raise ValueError("human access Action mode must match the verified promotion source")
        quorum = 2 if case.intent.requested_role in {Role.APPROVER, Role.OWNER} else 1
        material = HumanAccessExecutionMaterial.model_validate(
            {
                "action_json": canonical_human_access_json(action.model_dump(mode="json")),
                "subject_id": plan.subject_id,
                "group_id": plan.group_id,
                "requested_role": case.intent.requested_role.value,
                "requester_ref": case.intent.requester_ref,
                "case_record_digest": before,
                "role_groups_digest": human_access_record_digest(
                    {role.value: group for role, group in groups.items()}
                ),
                "promotion_record_digest": human_access_record_digest(dict(promotion_record)),
                "approval_ids": tuple(
                    str(uuid5(NAMESPACE_URL, f"fdai:human-access:{action.action_id}:{slot}"))
                    for slot in range(quorum)
                ),
                "recorded_at": now,
                "expires_at": now + timedelta(minutes=5),
            }
        )
        return await self.materials.retain(material)


__all__ = ["HumanAccessMaterialBuilder", "HumanAccessMaterialStore", "MATERIAL_PREFIX"]
