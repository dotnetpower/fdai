"""Checklist completeness is deterministic and never supplies human authority."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai_service_contracts.handover_checklist import (
    HANDOVER_SLOTS,
    HandoverReview,
    acceptance_complete,
    checklist_complete,
    checklist_defaults,
    checklist_digest,
    checklist_slots,
)


def _goal():
    return {
        "goal_id": "goal:example",
        "subject_ref": "human:subject",
        "agent_name": "Muninn",
        "revision": 9,
        "scope_ref": "scope:platform",
        "source_revision": "revision:1",
        "prompt_ref": "template:v1",
        "evidence": [
            {
                "slot": slot,
                "evidence_ref": "doc:example:v1",
                "digest": "a" * 64,
                "kind": "document",
            }
            for slot in HANDOVER_SLOTS
        ],
        **checklist_defaults(),
    }


@pytest.mark.parametrize("missing", HANDOVER_SLOTS)
def test_each_required_slot_is_necessary_and_never_implied_by_other_slots(missing):
    goal = _goal()
    goal["evidence"] = [item for item in goal["evidence"] if item["slot"] != missing]
    assert not checklist_complete(goal)


def test_complete_slots_are_not_acceptance_without_independent_reviews():
    goal = _goal()
    assert checklist_complete(goal)
    assert not acceptance_complete(goal)
    digest = checklist_digest(goal)
    goal["owner_review"] = HandoverReview(
        reviewer_ref="human:owner",
        goal_revision=7,
        evidence_digest=digest,
        reviewed_at=datetime(2026, 9, 14, tzinfo=UTC),
    ).model_dump(mode="json")
    assert not acceptance_complete(goal)
    goal["backup_review"] = {**goal["owner_review"], "reviewer_ref": "HUMAN:OWNER"}
    assert not acceptance_complete(goal)
    goal["backup_review"]["reviewer_ref"] = "human:backup"
    assert acceptance_complete(goal)


@pytest.mark.parametrize(
    "field,value",
    [
        ("subject_ref", "human:other"),
        ("scope_ref", "scope:other"),
        ("source_revision", "revision:2"),
        ("high_impact", False),
        ("agent_name", "Thor"),
    ],
)
def test_review_digest_binds_every_scope_and_authority_relevant_field(field, value):
    goal = _goal()
    assert checklist_digest(goal) != checklist_digest({**goal, field: value})


def test_duplicate_evidence_or_conflicting_exemption_is_not_extra_coverage():
    goal = _goal()
    goal["evidence"].append(dict(goal["evidence"][0]))
    with pytest.raises(ValueError, match="already"):
        checklist_slots(goal)
    goal = _goal()
    goal["slot_exemptions"] = {HANDOVER_SLOTS[0]: "reason:outside"}
    with pytest.raises(ValueError):
        checklist_slots(goal)


def test_legacy_or_unknown_requirements_never_gain_acceptance_by_default():
    goal = _goal()
    for changed in (
        {"checklist_version": None},
        {"required_slots": []},
        {"required_slots": list(reversed(HANDOVER_SLOTS))},
    ):
        with pytest.raises(ValueError):
            checklist_complete({**goal, **changed})


@pytest.mark.parametrize(
    "reviewer,revision",
    [
        ("human:subject", 7),
        (" human:owner ", 7),
        ("human:owner", 9),
    ],
)
def test_self_ambiguous_identity_or_future_revision_is_not_accepted(reviewer, revision):
    goal = _goal()
    review = {
        "reviewer_ref": reviewer,
        "goal_revision": revision,
        "evidence_digest": checklist_digest(goal),
        "reviewed_at": datetime(2026, 9, 14, tzinfo=UTC).isoformat(),
    }
    goal["owner_review"] = review
    goal["backup_review"] = {**review, "reviewer_ref": "human:backup", "goal_revision": 8}
    assert not acceptance_complete(goal)


def test_service_contracts_handover_hardening_rounds_h026_to_h035() -> None:
    from fdai_service_contracts.handover import (
        HandoverDraftOutcome,
        HandoverPerson,
        HandoverSourceSpan,
        RepositoryHandoverDraft,
        StewardKind,
        StewardResponsibility,
        StewardshipDraft,
        StewardshipInput,
        StewardshipMergeRecord,
        StewardshipSubject,
    )
    from fdai_service_contracts.handover_knowledge import notice_for_source
    from fdai_service_contracts.handover_observation import handover_observation_fields
    from fdai_service_contracts.stewardship_activation import __all__ as activation_exports

    # H026-H029: handover contract validation
    with pytest.raises(ValueError, match="non-empty"):
        StewardshipSubject(
            kind=StewardKind.USER,
            oid="   ",
            responsibility=StewardResponsibility.ACCOUNTABLE,
        )
    with pytest.raises(ValueError, match="non-empty"):
        StewardshipInput(version=1, revision="   ", maintainers=("m1",))
    with pytest.raises(ValueError, match="non-empty"):
        HandoverSourceSpan(doc_id="   ", line=1, quote="q")
    with pytest.raises(ValueError, match="non-empty"):
        HandoverPerson(display_name="   ")
    with pytest.raises(ValueError, match="non-empty"):
        StewardshipDraft(outcome=HandoverDraftOutcome.ABSTAINED, warnings=("   ",))
    with pytest.raises(ValueError, match="non-empty"):
        StewardshipMergeRecord(
            delivery_id=" ",
            pr_ref="p",
            actor_identity="a",
            merge_commit_sha="s",
            merged_yaml="y",
        )
    with pytest.raises(ValueError, match="content_sha256"):
        RepositoryHandoverDraft(
            delivery_id="d1",
            repository="org/repo",
            actor_identity="u1",
            source_ref="refs/heads/main",
            content="hello",
            content_sha256="0" * 64,
        )

    # H030-H035: tuple support, digest required fields, notice_for_source, observation, activation
    goal = _goal()
    goal["required_slots"] = tuple(HANDOVER_SLOTS)
    goal["evidence"] = tuple(goal["evidence"])
    assert checklist_complete(goal)
    with pytest.raises(ValueError, match="non-empty goal_id"):
        checklist_digest({**goal, "goal_id": "   "})
    with pytest.raises(ValueError, match="positive integer"):
        notice_for_source({**goal, "revision": True}, source="core", at=datetime.now(UTC))
    observed = handover_observation_fields(goal)
    assert len(observed["evidence"]) == len(HANDOVER_SLOTS)
    assert "StewardshipCandidateActivationBody" in activation_exports
