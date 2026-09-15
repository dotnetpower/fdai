"""Review-only artifacts from synthetic, independently recorded removal effects."""

from __future__ import annotations

from dataclasses import replace

import pytest
import yaml
from fdai.core.human_assignment import (
    AssignmentOwnershipCoordinator,
    AssignmentReconciler,
    AssignmentState,
    DutyBinding,
    EffectKind,
    ProviderSubject,
    VerifiedOwnershipMerge,
    render_assignment_ownership_yaml,
)
from fdai.core.human_assignment.iam_request import AssignmentIamRequestReader
from fdai.core.human_assignment.replacement import ReplacementCoveragePlanner
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty, load_stewardship_from_mapping
from fdai.core.stewardship.names import AGENT_NAMES
from fdai.runtime.human_assignment_reconciliation import AssignmentReconciliationWorker
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.remediation_pr import RecordingRemediationPrPublisher
from fdai_core_service.assignment_outcome_consumer import AssignmentOutcomeConsumer
from tests.core.human_assignment.test_revocation import (
    NOW,
    OLD_SUBJECT,
    _cases,
    _effect,
    _intent,
    _old,
    _removed,
    _reviewed,
)

PRIMARY = "00000000-0000-0000-0000-000000000011"
BACKUP = "00000000-0000-0000-0000-000000000012"


def _base():
    def steward(subject, duty):
        return {"kind": "user", "id": subject, "responsibility": "accountable", "duty": duty}

    return load_stewardship_from_mapping(
        {
            "stewardship": {
                "version": 2,
                "maintainers": [{"oid": PRIMARY}, {"oid": BACKUP}],
                "channels": {OLD_SUBJECT: "teams-hil-prd"},
                "agents": {
                    name: {
                        "stewards": [
                            *([steward(OLD_SUBJECT, "primary")] if name == "Thor" else []),
                            steward(PRIMARY, "primary"),
                            steward(BACKUP, "backup"),
                        ]
                    }
                    for name in AGENT_NAMES
                },
            }
        },
        environ={},
    )


async def _coordinator():
    cases = await _cases()
    for case_id, subject, duty in (
        ("primary", PRIMARY, Duty.PRIMARY),
        ("backup", BACKUP, Duty.BACKUP),
    ):
        replacement = replace(
            _old(),
            case_id=case_id,
            intent=replace(
                _old().intent,
                idempotency_key=case_id,
                subject=ProviderSubject("entra", subject),
                duty_bindings=(DutyBinding("Thor", duty, "scope:platform"),),
            ),
        )
        await cases.store.write_state(f"human_assignment:case:{case_id}", replacement.to_dict())
    return AssignmentOwnershipCoordinator(
        cases, cases.store, RecordingRemediationPrPublisher(), InMemoryEventBus(), "iam.raw"
    )


async def test_approved_removal_emits_only_replay_stable_shadow_review_request():
    coordinator = await _coordinator()
    approved = await _reviewed(coordinator.cases)
    for _ in range(2):
        await coordinator.request_revocation(case_id=approved.case_id, expected_revision=3)
    stream = coordinator.event_bus.subscribe("iam.raw", "test")
    first, replay = await anext(stream), await anext(stream)
    assert first.payload == replay.payload
    assert first.payload["mode"] == "shadow"
    proposal = await AssignmentIamRequestReader(coordinator.cases).read(first.payload["payload"])
    assert proposal["action_type"] == "ops.revoke-human-access"
    assert proposal["resolved_autonomy_ceiling"] == "shadow_only"
    assert proposal["params"]["replacement_revisions"] == {"primary": 7, "backup": 7}
    assert not coordinator.pr_publisher.records
    assert (await coordinator.cases.get_case("old")).state is AssignmentState.ACTIVE


async def test_reviewed_plan_keeps_exact_identity_across_its_own_hold_and_retries():
    coordinator = await _coordinator()
    approved = await _reviewed(coordinator.cases)
    planner = ReplacementCoveragePlanner(coordinator.cases, {Role.READER: "group:reader"})
    first = await planner.plan_revocation(case_id=approved.case_id, expected_revision=3)
    assert await planner.plan_revocation(case_id=approved.case_id, expected_revision=3) == first
    applying = await coordinator.cases.begin_iam_apply(
        case_id=approved.case_id, expected_revision=3, actor_ref="Thor"
    )
    resumed = await planner.plan_revocation(case_id=applying.case_id, expected_revision=4)
    assert resumed.removal == first.removal
    assert resumed.replacement_revisions == first.replacement_revisions
    with pytest.raises(ValueError, match="exact"):
        await planner.plan_revocation(case_id=applying.case_id, expected_revision=3)


async def test_matching_removal_merge_closes_case_without_regrant_or_unrelated_map_changes():
    coordinator = await _coordinator()
    removed = await _removed(coordinator.cases)
    base = _base()
    opened, proposal = await coordinator.open_proposal(
        case_id=removed.case_id, expected_revision=removed.revision, actor_ref="delivery", base=base
    )
    patch = coordinator.pr_publisher.records[0].patch
    changed = load_stewardship_from_mapping(yaml.safe_load(patch), environ={})
    assert changed.maintainers == base.maintainers
    assert changed.channels == base.channels
    assert {person.id for person in changed.agent("Thor").stewards} == {PRIMARY, BACKUP}
    for name in AGENT_NAMES:
        if name != "Thor":
            assert changed.agent(name) == base.agent(name)
    before_audit = tuple(coordinator.store.audit_entries)
    with pytest.raises(ValueError, match="does not match"):
        await coordinator.record_verified_merge(
            case_id=opened.case_id,
            expected_revision=opened.revision,
            actor_ref="verified-merge",
            merge=VerifiedOwnershipMerge(proposal.pr_ref, "a" * 40, patch + "\n", NOW),
        )
    assert tuple(coordinator.store.audit_entries) == before_audit
    merge = VerifiedOwnershipMerge(proposal.pr_ref, "a" * 40, patch, NOW)
    closed = await coordinator.record_verified_merge(
        case_id=opened.case_id,
        expected_revision=opened.revision,
        actor_ref="verified-merge",
        merge=merge,
    )
    assert closed.state is AssignmentState.REVOKED
    assert (
        await coordinator.record_verified_merge(
            case_id=closed.case_id,
            expected_revision=closed.revision,
            actor_ref="verified-merge",
            merge=merge,
        )
        == closed
    )
    assert len(coordinator.pr_publisher.records) == 1
    assert [event async for event in coordinator.event_bus.subscribe("iam.raw", "no-regrant")] == []


@pytest.mark.parametrize(
    "drift",
    ["replacement_revision", "replacement_state", "missing_old", "old_duty", "missing_backup"],
)
async def test_drift_after_iam_removal_holds_duty_artifact_without_publishing(drift):
    coordinator = await _coordinator()
    removed = await _removed(coordinator.cases)
    base = _base()
    if drift.startswith("replacement_"):
        replacement = await coordinator.cases.get_case("primary")
        replacement = (
            replace(replacement, revision=8)
            if drift == "replacement_revision"
            else replace(replacement, state=AssignmentState.DEGRADED, degraded_reason="unavailable")
        )
        await coordinator.store.write_state("human_assignment:case:primary", replacement.to_dict())
    else:
        from fdai.core.human_assignment.ownership import _base_mapping

        raw = _base_mapping(base)
        stewards = raw["stewardship"]["agents"]["Thor"]["stewards"]
        if drift == "old_duty":
            stewards[0]["duty"] = "backup"
        else:
            target = OLD_SUBJECT if drift == "missing_old" else BACKUP
            stewards[:] = [person for person in stewards if person["id"] != target]
            if drift == "missing_backup":
                stewards.append(
                    {
                        "kind": "user",
                        "id": "00000000-0000-0000-0000-000000000099",
                        "responsibility": "accountable",
                        "duty": "backup",
                    }
                )
        base = load_stewardship_from_mapping(raw, environ={})
    with pytest.raises(ValueError):
        await coordinator.open_proposal(
            case_id=removed.case_id,
            expected_revision=removed.revision,
            actor_ref="delivery",
            base=base,
        )
    assert not coordinator.pr_publisher.records
    assert (await coordinator.cases.get_case("old")).state is AssignmentState.DEGRADED


async def test_reconciliation_requires_sealed_review_not_just_a_stored_effect():
    coordinator = await _coordinator()
    removed = await _removed(coordinator.cases)
    consumer = AssignmentOutcomeConsumer(coordinator.store, coordinator, _base())
    worker = AssignmentReconciliationWorker(
        AssignmentReconciler(store=coordinator.store),
        removal_artifact=consumer.reconcile_revocation,
    )
    assert await worker.run_once() >= 1
    assert not coordinator.pr_publisher.records
    assert (await coordinator.cases.get_case(removed.case_id)).state is AssignmentState.IAM_REVOKED


async def test_verified_removal_cannot_repeat_iam_dispatch():
    coordinator = await _coordinator()
    removed = await _removed(coordinator.cases)
    with pytest.raises(ValueError):
        await coordinator.cases.begin_iam_apply(
            case_id=removed.case_id, expected_revision=removed.revision, actor_ref="Thor"
        )
    with pytest.raises(ValueError):
        await coordinator.cases.record_effect(
            case_id=removed.case_id,
            expected_revision=removed.revision,
            receipt=replace(_effect(EffectKind.IAM), digest="c" * 64),
            actor_ref="Thor",
        )


def test_grant_renderer_never_reinterprets_revocation_as_an_additive_assignment():
    with pytest.raises(ValueError, match="revocation"):
        render_assignment_ownership_yaml(_base(), _intent())


async def test_interrupted_original_closure_stays_held_until_exact_merge_replay(monkeypatch):
    coordinator = await _coordinator()
    removed = await _removed(coordinator.cases)
    opened, proposal = await coordinator.open_proposal(
        case_id=removed.case_id,
        expected_revision=removed.revision,
        actor_ref="delivery",
        base=_base(),
    )
    merge = VerifiedOwnershipMerge(
        proposal.pr_ref, "a" * 40, coordinator.pr_publisher.records[0].patch, NOW
    )
    write = coordinator.store.compare_and_set_state_with_audit
    armed = True

    async def fail_original_once(key, value, **kwargs):
        nonlocal armed
        if armed and key == "human_assignment:case:old" and value["state"] == "superseded":
            armed = False
            raise OSError("synthetic closure interruption")
        return await write(key, value, **kwargs)

    monkeypatch.setattr(coordinator.store, "compare_and_set_state_with_audit", fail_original_once)
    with pytest.raises(OSError):
        await coordinator.record_verified_merge(
            case_id=opened.case_id,
            expected_revision=opened.revision,
            actor_ref="verified-merge",
            merge=merge,
        )
    current = await coordinator.cases.get_case(opened.case_id)
    assert current.state is AssignmentState.REVOKED
    assert (await coordinator.cases.get_case("old")).state is AssignmentState.DEGRADED
    assert (
        await coordinator.record_verified_merge(
            case_id=current.case_id,
            expected_revision=current.revision,
            actor_ref="verified-merge",
            merge=merge,
        )
        == current
    )
    assert (await coordinator.cases.get_case("old")).state is AssignmentState.SUPERSEDED
    assert len(coordinator.pr_publisher.records) == 1
