"""Read-only replacement coverage planning before any access or duty removal."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from fdai.core.human_assignment.coverage import approval_quorum_satisfied, normalize_principal_ref
from fdai.core.human_assignment.model import AssignmentCase, AssignmentState
from fdai.core.human_assignment.revocation_target import require_revocation_target
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty
from fdai.shared.providers.human_access import HumanAccessOperation, HumanAccessPlan


@dataclass(frozen=True, slots=True)
class ReplacementCoveragePlan:
    """An inert plan, not approval, current membership proof, or a grant to dispatch."""

    removal: HumanAccessPlan
    replacement_revisions: Mapping[str, int]
    covered_slots: tuple[tuple[str, str], ...]
    remaining_steps: tuple[str, ...] = (
        "independent_revoke_review",
        "current_replacement_readback",
        "seven_safeguards_and_promotion",
        "thor_revoke_and_independent_verification",
        "reviewed_old_duty_removal",
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "replacement_revisions", MappingProxyType(dict(self.replacement_revisions))
        )


@dataclass(frozen=True, slots=True)
class ReplacementCoveragePlanner:
    """Resolve exact canonical replacement snapshots without changing either assignment."""

    cases: AssignmentCaseService
    role_group_ids: Mapping[Role, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "role_group_ids", MappingProxyType(dict(self.role_group_ids)))

    async def plan_revocation(
        self, *, case_id: str, expected_revision: int
    ) -> ReplacementCoveragePlan:
        """Resolve a separately approved removal without borrowing the original grant reviews."""
        removal = await self.cases.get_case(case_id)
        if (
            type(expected_revision) is not int
            or removal.revision != expected_revision
            or removal.intent.revocation is None
            or removal.state
            not in {
                AssignmentState.APPROVED,
                AssignmentState.IAM_APPLYING,
                AssignmentState.DEGRADED,
            }
            or removal.effect_receipts
            or not approval_quorum_satisfied(removal.intent, removal.reviews)
        ):
            raise ValueError("revocation plan requires its own exact independently reviewed case")
        original = await require_revocation_target(
            self.cases.store, removal.intent, revocation_case_id=case_id, allow_held=True
        )
        return await self._plan(
            original,
            replacement_revisions=removal.intent.revocation.replacement_revisions,
            removal_case_id=case_id,
            idempotency_key=f"human-access-revoke:{case_id}",
        )

    async def plan(
        self,
        *,
        case_id: str,
        expected_revision: int,
        replacement_revisions: Mapping[str, int],
    ) -> ReplacementCoveragePlan:
        """Require independently converged, distinct replacements for every old duty scope."""
        if not 1 <= len(replacement_revisions) <= 30 or case_id in replacement_revisions:
            raise ValueError("replacement coverage requires bounded independent cases")
        current = await self.cases.get_case(case_id)
        _active_revision(current, expected_revision)
        return await self._plan(
            current,
            replacement_revisions=replacement_revisions,
            removal_case_id=current.case_id,
            idempotency_key=f"human-access-revoke:{current.case_id}:{current.revision}",
        )

    async def _plan(
        self,
        current: AssignmentCase,
        *,
        replacement_revisions: Mapping[str, int],
        removal_case_id: str,
        idempotency_key: str,
    ) -> ReplacementCoveragePlan:
        if current.intent.subject.provider != "entra":
            raise ValueError("replacement provider is unsupported")
        replacements: list[AssignmentCase] = []
        for replacement_id, revision in replacement_revisions.items():
            replacement = await self.cases.get_case(replacement_id)
            _active_revision(replacement, revision)
            if (
                normalize_principal_ref(replacement.intent.subject.subject_id)
                == normalize_principal_ref(current.intent.subject.subject_id)
                or replacement.intent.subject.provider != current.intent.subject.provider
            ):
                raise ValueError("replacement must be a distinct subject in the same provider")
            replacements.append(replacement)
        covered: list[tuple[str, str]] = []
        for binding in current.intent.duty_bindings:
            subjects_by_duty: dict[Duty, set[str]] = {}
            for replacement in replacements:
                if replacement.intent.requested_role is Role.BREAK_GLASS:
                    raise ValueError("emergency membership cannot prove routine coverage")
                for proposed in replacement.intent.duty_bindings:
                    if (proposed.agent_name, proposed.scope_ref.casefold()) != (
                        binding.agent_name,
                        binding.scope_ref.casefold(),
                    ):
                        continue
                    subjects_by_duty.setdefault(proposed.duty, set()).add(
                        normalize_principal_ref(replacement.intent.subject.subject_id)
                    )
            primaries = subjects_by_duty.get(Duty.PRIMARY, set())
            fallback = subjects_by_duty.get(Duty.BACKUP, set()) | subjects_by_duty.get(
                Duty.ESCALATION, set()
            )
            if len(primaries) != 1 or not (fallback - primaries):
                raise ValueError(
                    "replacement needs one primary and a distinct live fallback per scope"
                )
            covered.append((binding.agent_name, binding.scope_ref))
        group = self.role_group_ids.get(current.intent.requested_role)
        if group is None or current.intent.requested_role is Role.BREAK_GLASS:
            raise ValueError("removal target role has no routine allowlisted group")
        await self._require_no_other_role_demand(current)
        return ReplacementCoveragePlan(
            removal=HumanAccessPlan(
                case_id=removal_case_id,
                subject_id=current.intent.subject.subject_id,
                group_id=group,
                operation=HumanAccessOperation.REVOKE,
                idempotency_key=idempotency_key,
            ),
            replacement_revisions=replacement_revisions,
            covered_slots=tuple(covered),
        )

    async def _require_no_other_role_demand(self, current: AssignmentCase) -> None:
        """Preserve another grant's active or uncertain membership until explicitly resolved."""
        offset = 0
        while offset < 1000:
            rows, total = await self.cases.store.read_state_page(
                "human_assignment:case:", limit=100, offset=offset
            )
            if total > 1000:
                raise ValueError("replacement role-demand evidence exceeds the bounded scan")
            for row in rows:
                other = AssignmentCase.from_dict(dict(row))
                if (
                    other.case_id != current.case_id
                    and other.intent.revocation is None
                    and other.state
                    in {
                        AssignmentState.ACTIVE,
                        AssignmentState.IAM_APPLYING,
                        AssignmentState.DEGRADED,
                    }
                    and other.intent.requested_role is current.intent.requested_role
                    and other.intent.subject.provider == current.intent.subject.provider
                    and normalize_principal_ref(other.intent.subject.subject_id)
                    == normalize_principal_ref(current.intent.subject.subject_id)
                ):
                    raise ValueError("membership is still required by another unresolved grant")
            offset += len(rows)
            if offset >= total:
                return
            if not rows:
                raise ValueError("replacement role-demand evidence is incomplete")
        raise ValueError("replacement role-demand scan did not complete")


def _active_revision(case: AssignmentCase, expected: int) -> None:
    if (
        not isinstance(expected, int)
        or isinstance(expected, bool)
        or case.revision != expected
        or case.state is not AssignmentState.ACTIVE
        or not case.has_required_effects
    ):
        raise ValueError("replacement requires exact active revision and both effect receipts")


__all__ = ["ReplacementCoveragePlan", "ReplacementCoveragePlanner"]
