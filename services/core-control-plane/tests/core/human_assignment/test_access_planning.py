"""Read-only Core planning and shared contract compatibility."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.human_assignment import AssignmentCaseService
from fdai.core.human_assignment.access_planning import HumanAccessPlanner
from fdai.core.rbac.roles import Role
from fdai.shared.providers import human_access as legacy
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts import human_access as shared
from tests.core.human_assignment.test_access_apply import _ownership_merged


def test_core_and_executor_share_one_membership_contract_identity() -> None:
    for name in shared.__all__:
        assert getattr(legacy, name) is getattr(shared, name)


async def test_planning_retains_case_state_and_does_not_hold_a_provider() -> None:
    store = InMemoryStateStore()
    cases = AssignmentCaseService(store)
    case = await _ownership_merged(cases)
    groups = {Role.READER: "group:reader"}
    planner = HumanAccessPlanner(cases, groups)
    groups[Role.READER] = "group:changed"
    before = await cases.get_case(case.case_id)
    value = await planner.plan(case_id=case.case_id, expected_revision=case.revision)
    assert value.group_id == "group:reader"
    assert await cases.get_case(case.case_id) == before
    assert not hasattr(planner, "execute") and not hasattr(planner, "provisioner")
    inverse = replace(value, operation=shared.HumanAccessOperation.REVOKE)
    assert value.membership_lock_key == inverse.membership_lock_key


@pytest.mark.parametrize("revision", [True, 0, -1, "5", 999])
async def test_planning_refuses_nonexact_or_coerced_revision(revision) -> None:
    cases = AssignmentCaseService(InMemoryStateStore())
    case = await _ownership_merged(cases)
    with pytest.raises(ValueError, match="exact current"):
        await HumanAccessPlanner(cases, {Role.READER: "group:reader"}).plan(
            case_id=case.case_id, expected_revision=revision
        )


async def test_planner_command_receipt_and_iam_request_validation_branches() -> None:
    from fdai.core.human_assignment.command_receipt import AssignmentCommandReceipt
    from fdai.core.human_assignment.iam_request import AssignmentIamRequestReader
    from fdai.core.human_assignment.model import AssignmentState, ProviderSubject

    # AssignmentCommandReceipt validation and serialization
    digest = "a" * 64
    receipt = AssignmentCommandReceipt(f"operator-{digest[:32]}", digest)
    assert AssignmentCommandReceipt.from_dict(receipt.to_dict()) == receipt
    with pytest.raises(ValueError, match="MUST be strings"):
        AssignmentCommandReceipt(123, digest)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="MUST be SHA-256"):
        AssignmentCommandReceipt("operator-short", "not-a-sha")
    with pytest.raises(ValueError, match="MUST match its digest"):
        AssignmentCommandReceipt("operator-" + "b" * 32, digest)
    with pytest.raises(ValueError, match="fields are invalid"):
        AssignmentCommandReceipt.from_dict({"proposal_id": receipt.proposal_id})

    # HumanAccessPlanner error branches
    store = InMemoryStateStore()
    cases = AssignmentCaseService(store)
    case = await _ownership_merged(cases)
    planner = HumanAccessPlanner(cases, {Role.READER: "group:reader"})

    # revocation_case_id held
    held = replace(
        case,
        state=AssignmentState.DEGRADED,
        degraded_reason="revocation_pending",
        revocation_case_id="rev-1",
    )
    await store.write_state(f"human_assignment:case:{case.case_id}", held.to_dict())
    with pytest.raises(ValueError, match="revocation-held"):
        await planner.plan(case_id=case.case_id, expected_revision=held.revision)

    # non-entra provider
    non_entra = replace(
        case,
        intent=replace(case.intent, subject=ProviderSubject("github", "user-1")),
    )
    await store.write_state(f"human_assignment:case:{case.case_id}", non_entra.to_dict())
    with pytest.raises(ValueError, match="provider is unsupported"):
        await planner.plan(case_id=case.case_id, expected_revision=non_entra.revision)

    # unreviewed case
    unreviewed = replace(
        case,
        state=AssignmentState.DRAFT,
        reviews=(),
        effect_receipts=(),
    )
    await store.write_state(f"human_assignment:case:{case.case_id}", unreviewed.to_dict())
    with pytest.raises(ValueError, match="independent case approval"):
        await planner.plan(case_id=case.case_id, expected_revision=unreviewed.revision)

    # reviewed but state not OWNERSHIP_MERGED / IAM_APPLYING / DEGRADED
    pr_open = replace(
        case,
        state=AssignmentState.OWNERSHIP_PR_OPEN,
        effect_receipts=(),
    )
    await store.write_state(f"human_assignment:case:{case.case_id}", pr_open.to_dict())
    with pytest.raises(ValueError, match="merged ownership effect"):
        await planner.plan(case_id=case.case_id, expected_revision=pr_open.revision)

    # DEGRADED without ownership receipt
    degraded_no_own = replace(
        case,
        state=AssignmentState.DEGRADED,
        degraded_reason="failed",
        effect_receipts=(),
    )
    await store.write_state(f"human_assignment:case:{case.case_id}", degraded_no_own.to_dict())
    with pytest.raises(ValueError, match="ownership effect receipt"):
        await planner.plan(case_id=case.case_id, expected_revision=degraded_no_own.revision)

    # Restore valid case and test missing/blank group
    await store.write_state(f"human_assignment:case:{case.case_id}", case.to_dict())
    with pytest.raises(ValueError, match="no routine allowlisted group"):
        await HumanAccessPlanner(cases, {Role.READER: "   "}).plan(
            case_id=case.case_id, expected_revision=case.revision
        )

    # AssignmentIamRequestReader branches
    reader = AssignmentIamRequestReader(cases)
    valid_notice = {
        "case_id": case.case_id,
        "expected_revision": case.revision,
        "ownership_digest": "digest-ownership",
        "ownership_ref": "github:pr-1",
    }
    proposal = await reader.read(valid_notice)
    assert proposal["action_type"] == "ops.apply-human-access"

    with pytest.raises(ValueError, match="notice fields are invalid"):
        await reader.read({"case_id": case.case_id})
    with pytest.raises(ValueError, match="identity and revision are invalid"):
        await reader.read({**valid_notice, "expected_revision": True})
    with pytest.raises(ValueError, match="no longer matches"):
        await reader.read({**valid_notice, "expected_revision": case.revision + 1})
    with pytest.raises(ValueError, match="does not match the canonical effect"):
        await reader.read({**valid_notice, "ownership_digest": "wrong-digest"})

    await store.write_state(f"human_assignment:case:{case.case_id}", non_entra.to_dict())
    with pytest.raises(ValueError, match="reviewed supported assignment"):
        await reader.read(valid_notice)
