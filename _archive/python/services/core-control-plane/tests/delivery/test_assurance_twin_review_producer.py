"""Forseti publishes read-only reviews only from complete typed-proposal evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.assurance_twin import DeclaredPropertyEffect, TypedActionProposal
from fdai.delivery.assurance_twin_publication import (
    PUBLICATION_TOPIC,
    AssuranceTwinOutboxPublisher,
    AssuranceTwinPublicationEvent,
)
from fdai.shared.providers.projection import ResourceRef
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai_operator_service.assurance_twin_posture_projection import (
    assurance_twin_review_detail_projection,
)

from tests.delivery.assurance_twin_review_harness import (
    ACTION_TYPE,
    TARGET,
    UNRELATED,
    PublicAccessPolicy,
    TwinHarness,
    proposal,
    reviewed_effect,
    rule,
    what_if,
)

_AUTHORITY_FIELDS = {"approval", "approved", "approver", "executor_identity_ref", "promotion"}


@pytest.fixture
def now() -> datetime:
    """Pin one instant per test; writer admission still compares with the wall clock."""
    return datetime.now(UTC) - timedelta(seconds=1)


def _typed(parameters: dict[str, str]) -> TypedActionProposal:
    return TypedActionProposal.create(
        action_type=ACTION_TYPE,
        action_type_version="1.0.0",
        targets=(TARGET,),
        parameters=parameters,
    )


async def test_supported_typed_proposal_publishes_one_read_only_forseti_review(
    now: datetime,
) -> None:
    twin, bus = TwinHarness(now, effects=(reviewed_effect(),)), InMemoryEventBus()
    item = proposal()
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")

    assert (await twin.producer.review_pending()).recorded == 1
    [intake_row] = await twin.intake_rows()
    assert intake_row["status"] == "recorded" and intake_row["reason_code"] is None
    evaluated = twin.evaluator.evaluated[-1]
    assert evaluated.resources.keys() == {TARGET}
    assert evaluated.properties(TARGET) == {"public_access": "disabled"}
    publish_request = await twin.relayed_request(bus)
    assert publish_request.kind == "review"
    assert publish_request.source_key == item.proposal_ref
    assert await twin.writer.process(publish_request)
    assert (await twin.producer.review_pending()).reviewed == 1

    [review] = await twin.ledger.read_recent_change_reviews()
    assert review["pr_ref"] == review["review_key"] == item.proposal_ref
    assert review["verdict"] == "clear" and review["findings"] == []
    assert review["metadata"]["evidence_kind"] == "typed_action_proposal"
    assert review["metadata"]["proposal_digest"] == item.proposal_digest
    assert review["metadata"]["inventory_revision"] == twin.inventory.current
    assert review["mode"] == "shadow"
    detail = assurance_twin_review_detail_projection(
        {"value": review}, requested_review_key=review["review_key"]
    )
    assert detail is not None and detail["available"] is True

    publisher = AssuranceTwinOutboxPublisher(owner="Forseti", ledger=twin.ledger, bus=bus)
    assert await publisher.publish_pending() == 1
    assert await publisher.publish_pending() == 0
    [published] = [item async for item in bus.subscribe(PUBLICATION_TOPIC, "reader")]
    event = AssuranceTwinPublicationEvent.model_validate(published.payload)
    assert (event.kind, event.owner_agent) == ("review", "Forseti")
    assert event.execution_authority is False and event.activity.execution_authority is False
    assert event.current is False and event.publication_complete is False
    assert not _AUTHORITY_FIELDS & set(published.payload)
    assert not _AUTHORITY_FIELDS & set(published.payload["activity"])

    lineage = [
        entry["entry"]
        for entry in twin.store.audit_entries
        if entry["entry"].get("owner_agent") == "Saga"
    ]
    assert [entry["action_kind"] for entry in lineage] == [
        "assurance_twin.review_recorded",
        "assurance_twin.publication_acknowledged",
    ]
    assert {entry["subject_owner_agent"] for entry in lineage} == {"Forseti"}
    assert twin.intake_audit() == [
        ("assurance_twin_proposal_review_submitted", None),
        ("assurance_twin_proposal_review_recorded", None),
        ("assurance_twin_proposal_review_reviewed", None),
    ]
    assert all(
        entry["entry"].get("execution_authority") in (None, False)
        for entry in twin.store.audit_entries
    )
    assert await twin.store.verify_chain()


async def test_violating_typed_proposal_is_blocked_on_its_own_target(now: datetime) -> None:
    twin, bus = TwinHarness(now, effects=(reviewed_effect(),)), InMemoryEventBus()
    item = proposal("enabled")
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")

    assert (await twin.producer.review_pending()).recorded == 1
    assert await twin.writer.process(await twin.relayed_request(bus))
    [review] = await twin.ledger.read_recent_change_reviews()
    assert review["verdict"] == "blocked"
    assert [finding["resource_ref"] for finding in review["findings"]] == [TARGET.ref]


async def test_effect_on_a_property_no_rule_reads_is_unassessed_not_clear(now: datetime) -> None:
    effect = reviewed_effect(
        property_effects=(DeclaredPropertyEffect("network_rule", parameter="network_rule"),)
    )
    twin = TwinHarness(now, effects=(effect,))
    twin.inventory.target_properties = {"public_access": "disabled"}
    item = _typed({"network_rule": "allow-all"})
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")

    summary = await twin.producer.review_pending()

    assert (summary.recorded, summary.unavailable) == (0, 1)
    [intake_row] = await twin.intake_rows()
    assert (intake_row["status"], intake_row["reason_code"]) == ("unavailable", "effect_unassessed")
    assert twin.evaluator.evaluated[-1].properties(TARGET)["network_rule"] == "allow-all"
    assert await twin.evidence_rows() == ()
    assert await twin.ledger.read_recent_change_reviews() == ()


async def test_every_written_property_needs_an_applying_rule_input(now: datetime) -> None:
    effect = reviewed_effect(
        property_effects=(
            DeclaredPropertyEffect("network_rule", parameter="network_rule"),
            DeclaredPropertyEffect("public_access", constant_json='"disabled"'),
        )
    )
    twin = TwinHarness(now, effects=(effect,))
    twin.inventory.target_properties = {"public_access": "disabled"}
    item = _typed({"network_rule": "allow-all"})
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")

    assert (await twin.producer.review_pending()).unavailable == 1
    [intake_row] = await twin.intake_rows()
    assert intake_row["reason_code"] == "effect_unassessed"


async def test_effect_on_an_assessed_property_is_recorded_as_clear(now: datetime) -> None:
    twin, bus = TwinHarness(now, effects=(reviewed_effect(),)), InMemoryEventBus()
    twin.inventory.target_properties = {"public_access": "disabled"}
    item = proposal()
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")

    assert (await twin.producer.review_pending()).recorded == 1
    assert await twin.writer.process(await twin.relayed_request(bus))
    assert (await twin.producer.review_pending()).reviewed == 1
    [review] = await twin.ledger.read_recent_change_reviews()
    assert review["verdict"] == "clear"


def _network_twin(now: datetime, *, current: dict[str, object], property_ref: str) -> TwinHarness:
    twin = TwinHarness(
        now,
        effects=(
            reviewed_effect(
                property_effects=(
                    DeclaredPropertyEffect("network_acls", parameter="network_acls"),
                ),
            ),
        ),
    )
    twin.inventory.target_properties = {"public_access": "disabled", "network_acls": current}
    twin.evaluator.activate(
        PublicAccessPolicy(),
        generation_time=now - timedelta(minutes=2),
        rules=(rule("rule.object-storage.network-acls", property_ref),),
    )
    return twin


@pytest.mark.parametrize(
    ("current", "property_ref", "status"),
    [
        (
            {"default_action": "Allow"},
            "property.object-storage.network_acls.default_action",
            "unavailable",
        ),
        ({"default_action": "Allow"}, "property.object-storage.network_acls", "recorded"),
        (
            {"default_action": "Allow", "ip_rules": ["0.0.0.0/0"]},
            "property.object-storage.network_acls.default_action",
            "recorded",
        ),
    ],
)
async def test_nested_rewrite_needs_rule_inputs_for_every_changed_leaf(
    now: datetime, current: dict[str, object], property_ref: str, status: str
) -> None:
    twin = _network_twin(now, current=current, property_ref=property_ref)
    item = _typed_value({"default_action": "Deny", "ip_rules": ["0.0.0.0/0"]})
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")

    await twin.producer.review_pending()

    [intake_row] = await twin.intake_rows()
    assert intake_row["status"] == status
    if status == "unavailable":
        assert intake_row["reason_code"] == "effect_unassessed"
        assert await twin.evidence_rows() == ()


def _typed_value(network_acls: dict[str, object]) -> TypedActionProposal:
    return TypedActionProposal.create(
        action_type=ACTION_TYPE,
        action_type_version="1.0.0",
        targets=(TARGET,),
        parameters={"network_acls": network_acls},
    )


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("unsupported_action_type", "effect_model_unavailable"),
        ("missing_what_if", "what_if_missing"),
        ("stale_what_if", "what_if_stale"),
        ("incomplete_what_if", "what_if_incomplete"),
        ("conflicting_what_if", "what_if_conflict"),
        ("conflicting_targets", "what_if_conflict"),
        ("cross_revision_target", "target_outside_revision"),
        ("undeclared_parameter", "parameter_undeclared"),
    ],
)
async def test_unavailable_typed_proposals_never_record_review_evidence(
    now: datetime, case: str, reason: str
) -> None:
    effects = () if case == "unsupported_action_type" else (reviewed_effect(),)
    twin = TwinHarness(now, effects=effects)
    item = proposal()
    outside = proposal(targets=(ResourceRef("object-storage", "storage-not-in-revision"),))
    extra = _typed({"public_access": "disabled", "network_rule": "allow-all"})
    submitted: dict[str, Any] = {
        "unsupported_action_type": (item, what_if(item, now)),
        "missing_what_if": (item, None),
        "stale_what_if": (item, what_if(item, now, expires_at=now - timedelta(seconds=1))),
        "incomplete_what_if": (item, what_if(item, now, complete=False)),
        "conflicting_what_if": (item, what_if(proposal("enabled"), now)),
        "conflicting_targets": (item, what_if(item, now, affected_targets=(UNRELATED,))),
        "cross_revision_target": (outside, what_if(outside, now)),
        "undeclared_parameter": (extra, what_if(extra, now)),
    }
    typed, result = submitted[case]
    await twin.intake.submit(proposal=typed, what_if=result, correlation_id="c-1")

    assert (await twin.producer.review_pending()).unavailable == 1
    [intake_row] = await twin.intake_rows()
    assert (intake_row["status"], intake_row["reason_code"]) == ("unavailable", reason)
    assert await twin.evidence_rows() == ()
    assert await twin.ledger.read_recent_change_reviews() == ()
    assert twin.intake_audit()[-1] == ("assurance_twin_proposal_review_unavailable", reason)
    assert (await twin.producer.review_pending()).unavailable == 0


async def test_restart_and_redelivery_are_idempotent(now: datetime) -> None:
    twin, bus = TwinHarness(now, effects=(reviewed_effect(),)), InMemoryEventBus()
    item = proposal()
    first_key = await twin.intake.submit(
        proposal=item, what_if=what_if(item, now), correlation_id="c-1"
    )
    assert first_key == await twin.intake.submit(
        proposal=item, what_if=what_if(item, now), correlation_id="c-retry"
    )
    [pending] = await twin.intake.active()
    derivation = await twin.producer.review(pending)
    restarted = twin.restarted_producer((reviewed_effect(),))
    replay = await restarted.review(pending)
    assert derivation.recorded is not None and replay == derivation
    assert (await restarted.review_pending()).recorded == 1
    assert (await twin.restarted_producer((reviewed_effect(),)).review_pending()).recorded == 0
    assert len(await twin.evidence_rows()) == 1

    publish_request = await twin.relayed_request(bus)
    assert publish_request == derivation.recorded.request
    assert await twin.writer.process(publish_request)
    assert await twin.writer.process(publish_request)
    publisher = AssuranceTwinOutboxPublisher(owner="Forseti", ledger=twin.ledger, bus=bus)
    assert await publisher.publish_pending() == 1
    assert await publisher.publish_pending() == 0
    kinds = [entry["entry"].get("action_kind") for entry in twin.store.audit_entries]
    assert kinds.count("assurance_twin.review_recorded") == 1
    assert [kind for kind, _ in twin.intake_audit()].count(
        "assurance_twin_proposal_review_submitted"
    ) == 1


async def test_retired_proposed_iac_evidence_stays_unavailable(now: datetime) -> None:
    twin = TwinHarness(now, effects=(reviewed_effect(),))
    item = proposal()
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")
    derivation = await twin.producer.review((await twin.intake.active())[0])
    assert derivation.recorded is not None
    request = derivation.recorded.request
    [retained] = await twin.evidence_rows()
    key = "runtime:assurance-twin-evidence:" + request.idempotency_key.removeprefix("sha256:")
    legacy = {key: value for key, value in retained.items() if key != "typed_proposal"}
    legacy["proposed_iac"] = {
        "source_revision": request.source_revision,
        "pr_ref": "example/project#1",
        "proposal_digest": "sha256:" + "0" * 64,
        "evidence_refs": ["plan:1"],
        "complete": True,
    }
    await twin.store.write_state(key, legacy)

    assert not await twin.writer.process(request)
    assert await twin.ledger.read_recent_change_reviews() == ()
