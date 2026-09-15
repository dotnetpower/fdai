"""Reviewed scoped artifact consumption with synthetic publisher and independent readback."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fdai.core.executor.lock import ResourceLockManager
from fdai.core.human_assignment.scoped_duty_ownership import (
    ScopedDutyMergeObservation,
    ScopedDutyOwnership,
    scoped_artifact,
)
from fdai.shared.providers.testing.remediation_pr import RecordingRemediationPrPublisher
from tests.core.human_assignment.test_scoped_duty_cases import AT, SECOND, pending, review
from tests.core.human_assignment.test_scoped_duty_cases import runtime as runtime


async def approved(runtime):
    service = runtime[0]
    case = await pending(runtime)
    case = await review(service, case)
    return await review(service, case, actor=SECOND, number=4)


def delivery(runtime):
    async def read(**fields):
        return ScopedDutyMergeObservation(
            **fields,
            merge_commit_sha="a" * 40,
            observed_at=AT,
            expires_at=AT + timedelta(seconds=60),
        )

    return ScopedDutyOwnership(
        runtime[0],
        RecordingRemediationPrPublisher(),
        ResourceLockManager(),
        SimpleNamespace(read=AsyncMock(side_effect=read)),
    )


async def test_artifact_replay_keeps_digest_and_never_writes_global_map_or_iam(runtime):
    case = await approved(runtime)
    owner = delivery(runtime)
    opened = await owner.open_proposal(case.case_id, expected_revision=case.revision)
    assert opened.state == "ownership_pr_open" and opened.merge_commit_sha is None
    again = await owner.open_proposal(case.case_id, expected_revision=opened.revision)
    assert again == opened and len(owner.publisher.records) == 1
    artifact = owner.publisher.records[0]
    assert artifact.patch_path == f"config/scoped-duty-plans/{case.case_id}.json"
    assert artifact.mode.value == "shadow" and "shadow" in artifact.labels
    assert scoped_artifact(opened) == scoped_artifact(case)
    content = json.loads(artifact.patch)
    assert (
        content["iam_authority"]
        is content["execution_authority"]
        is content["global_map_authority"]
        is False
    )
    assert not await owner.cases.store.read_states("human_assignment:case:", limit=10)
    assert await owner.cases.store.read_state(
        "human_assignment:scoped-artifact-intent:" + case.case_id
    )


async def test_publisher_dispatch_never_proves_reviewed_current_ownership(runtime):
    case = await approved(runtime)
    owner = delivery(runtime)
    opened = await owner.open_proposal(case.case_id, expected_revision=case.revision)
    owner.merges.read.side_effect = None
    owner.merges.read.return_value = None
    assert await owner.observe(opened) == ()


async def test_independent_exact_merge_supplies_only_current_scoped_projection(runtime):
    case = await approved(runtime)
    owner = delivery(runtime)
    opened = await owner.open_proposal(case.case_id, expected_revision=case.revision)
    rows = await owner.observe(opened)
    assert len(rows) == 1
    assert rows[0]["scope_ref"] == "scope:example" and rows[0]["agent_name"] == "Odin"
    assert rows[0]["primary_refs"] == ["human:primary"] and rows[0]["backup_refs"] == [
        "human:backup"
    ]
    assert rows[0]["execution_authority"] is False
    assert (await owner.cases.get(case.case_id)) == opened


@pytest.mark.parametrize("field", ["pr_ref", "path", "candidate_digest", "expires_at"])
async def test_independent_observer_mismatch_or_expiry_never_proves_ownership(runtime, field):
    case = await approved(runtime)
    owner = delivery(runtime)
    opened = await owner.open_proposal(case.case_id, expected_revision=case.revision)

    async def changed(**fields):
        fields.update(
            merge_commit_sha="a" * 40, observed_at=AT, expires_at=AT + timedelta(seconds=60)
        )
        fields[field] = AT if field == "expires_at" else "wrong"
        return ScopedDutyMergeObservation(**fields)

    owner.merges.read.side_effect = changed
    with pytest.raises(ValueError):
        await owner.observe(opened)


async def test_missing_independent_review_or_changed_source_prevents_publisher(runtime):
    case = await pending(runtime)
    owner = delivery(runtime)
    with pytest.raises(ValueError):
        await owner.open_proposal(case.case_id, expected_revision=case.revision)
    assert not owner.publisher.records
    case = await review(owner.cases, case)
    case = await review(owner.cases, case, actor=SECOND, number=4)
    runtime[2].is_current_owner.return_value = False
    with pytest.raises(PermissionError):
        await owner.open_proposal(case.case_id, expected_revision=case.revision)
    assert not owner.publisher.records


async def test_concurrent_drafts_are_target_serialized_and_idempotent(runtime):
    case = await approved(runtime)
    owner = delivery(runtime)
    results = await asyncio.gather(
        *(owner.open_proposal(case.case_id, expected_revision=case.revision) for _ in range(2)),
        return_exceptions=True,
    )
    assert len(owner.publisher.records) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1


async def test_failed_intent_audit_prevents_any_draft(runtime, monkeypatch):
    case = await approved(runtime)
    owner = delivery(runtime)
    monkeypatch.setattr(
        owner.cases.store,
        "write_state_with_audit_if_absent",
        AsyncMock(side_effect=RuntimeError("audit failed")),
    )
    with pytest.raises(RuntimeError):
        await owner.open_proposal(case.case_id, expected_revision=case.revision)
    assert not owner.publisher.records


async def test_expiry_after_draft_keeps_delivery_receipt_without_claiming_effect(runtime):
    case = await approved(runtime)
    owner = delivery(runtime)
    original = owner.publisher.publish

    async def slow(pr):
        result = await original(pr)
        runtime[1]["now"] = AT + timedelta(minutes=5)
        return result

    publisher = SimpleNamespace(records=owner.publisher.records, publish=slow)
    owner = ScopedDutyOwnership(owner.cases, publisher, owner.locks, owner.merges)
    opened = await owner.open_proposal(case.case_id, expected_revision=case.revision)
    assert opened.pr_ref and opened.state == "ownership_pr_open"
    with pytest.raises(ValueError):
        await owner.observe(opened)


async def test_projection_expiry_cannot_outlive_an_imminent_duty_transition(runtime):
    from fdai.core.human_assignment.scoped_duty_case_model import plan_expiry

    case = await approved(runtime)
    plan = case.plan()
    plan["bindings"][0]["binding"]["effective_until"] = (AT + timedelta(seconds=2)).isoformat()
    assert plan_expiry(plan) == AT + timedelta(seconds=2)
