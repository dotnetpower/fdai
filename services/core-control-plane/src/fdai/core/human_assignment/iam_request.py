"""Revalidate a matching ownership effect before proposing shadow IAM judgment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.core.human_assignment.coverage import approval_quorum_satisfied
from fdai.core.human_assignment.model import AssignmentState, EffectKind
from fdai.core.human_assignment.revocation_target import require_revocation_target
from fdai.core.human_assignment.service import AssignmentCaseService


@dataclass(frozen=True, slots=True)
class AssignmentIamRequestReader:
    """Resolve Core-owned case/effect evidence, never accept a bus identity as approval."""

    cases: AssignmentCaseService

    async def read(self, notice: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return a fresh-review-required proposal only for the exact merged case revision."""
        if set(notice) != {"case_id", "expected_revision", "ownership_digest", "ownership_ref"}:
            raise ValueError("IAM request notice fields are invalid")
        case_id, revision = notice["case_id"], notice["expected_revision"]
        if (
            not isinstance(case_id, str)
            or not 1 <= len(case_id) <= 256
            or not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 1
        ):
            raise ValueError("IAM request identity and revision are invalid")
        case = await self.cases.get_case(case_id)
        revoke = case.intent.revocation is not None
        expected_state = AssignmentState.APPROVED if revoke else AssignmentState.OWNERSHIP_MERGED
        if case.state is not expected_state or case.revision != revision:
            raise ValueError("IAM request no longer matches the current ownership revision")
        if case.intent.subject.provider != "entra" or not approval_quorum_satisfied(
            case.intent, case.reviews
        ):
            raise ValueError("IAM request requires a reviewed supported assignment")
        source = (
            await require_revocation_target(
                self.cases.store, case.intent, revocation_case_id=case_id
            )
            if revoke
            else case
        )
        ownership = next(
            (item for item in source.effect_receipts if item.kind is EffectKind.OWNERSHIP), None
        )
        if (
            ownership is None
            or ownership.digest != notice["ownership_digest"]
            or ownership.receipt_ref != notice["ownership_ref"]
        ):
            raise ValueError("IAM request ownership receipt does not match the canonical effect")
        return {
            "action_type": "ops.revoke-human-access" if revoke else "ops.apply-human-access",
            "resource_id": f"human-assignment:{case.case_id}",
            "params": {
                "case_id": case.case_id,
                "expected_revision": case.revision,
                **(
                    {"replacement_revisions": dict(case.intent.revocation.replacement_revisions)}
                    if case.intent.revocation is not None
                    else {}
                ),
            },
            "initiator_principal": case.intent.requester_ref,
            "quorum_required": (
                2 if case.intent.requested_role.value in {"Approver", "Owner"} else 1
            ),
            "risk_verdict": "hil",
            "reason": "assignment_iam_requires_current_human_review",
            "resolved_autonomy_ceiling": "shadow_only",
        }


__all__ = ["AssignmentIamRequestReader"]
