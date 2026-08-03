from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.huginn import Huginn
from fdai.agents.muninn import Muninn
from fdai.core.impact_analysis import AffectedSet, ChangeAssessment


async def test_huginn_publishes_change_and_muninn_keeps_revision() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    huginn = Huginn(bus=bus)
    muninn = Muninn()
    bus.subscribe("object.change", "Muninn", muninn.on_typed_message)

    event = await huginn.ingest(
        {
            "idempotency_key": "plan-1",
            "event_id": "event-1",
            "correlation_id": "correlation-1",
            "event_type": "iac.plan",
            "source": "gitops",
            "resource_id": "resource-1",
            "occurred_at": datetime(2026, 8, 4, tzinfo=UTC).isoformat(),
            "change": {
                "id": "change-1",
                "change_kind": "infrastructure",
                "intent_kind": "planned",
                "actor_ref": "pipeline-principal",
                "status": "planned",
                "desired_state_digest": "sha256:desired",
                "plan_receipt_ref": "plan:1",
            },
        }
    )

    changes = bus.messages_on("object.change")
    assert len(changes) == 1
    assert changes[0].principal == "Huginn"
    assert event is not None
    assert all(
        changes[0].payload[key] == value for key, value in event["normalized_change"].items()
    )
    stored = muninn.get_context("changes", "change-1")
    assert stored is not None
    assert stored["change"]["desired_state_digest"] == "sha256:desired"
    assert len(muninn.state_store.data["change_revisions"]) == 1


async def test_non_change_event_does_not_publish_change() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    await Huginn(bus=bus).ingest(
        {
            "id": "event-1",
            "event_type": "health.sample",
            "resource_id": "resource-1",
        }
    )
    assert bus.messages_on("object.change") == []


async def test_change_without_authoritative_time_fails_before_publish() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    with pytest.raises(ValueError, match="occurred_at"):
        await Huginn(bus=bus).ingest(
            {
                "id": "event-1",
                "event_type": "iac.plan",
                "source": "gitops",
                "resource_id": "resource-1",
            }
        )
    assert bus.messages_on("object.event") == []
    assert bus.messages_on("object.change") == []


async def test_muninn_preserves_distinct_change_revisions() -> None:
    muninn = Muninn()
    baseline = {
        "producer_principal": "Huginn",
        "id": "change-1",
        "status": "planned",
    }
    await muninn.on_typed_message("object.change", baseline)
    await muninn.on_typed_message("object.change", {**baseline, "status": "completed"})
    await muninn.on_typed_message("object.change", {**baseline, "status": "completed"})

    assert len(muninn.state_store.data["change_revisions"]) == 2
    latest = muninn.get_context("changes", "change-1")
    assert latest is not None
    assert latest["change"]["status"] == "completed"


class _ChangeAssessor:
    def __init__(self, *, review_required: bool) -> None:
        self.review_required = review_required
        self.graph_fresh_values: list[bool] = []

    async def assess(
        self,
        change: dict[str, object],
        *,
        graph_fresh: bool,
        unresolved_conflicts: tuple[str, ...] = (),
    ) -> ChangeAssessment:
        del unresolved_conflicts
        self.graph_fresh_values.append(graph_fresh)
        reasons = ("graph_stale",) if self.review_required else ()
        return ChangeAssessment(
            change_id=str(change["id"]),
            correlation_id=str(change["correlation_id"]),
            target_ref=str(change["target_ref"]),
            occurred_at=datetime.fromisoformat(str(change["occurred_at"])),
            affected_set=AffectedSet(
                direct_targets=(str(change["target_ref"]),),
                runtime_dependents=(),
                protected_services=("service-1",),
                protected_objectives=("objective-1",),
                control_dependencies=(),
                graph_revision="revision-1",
            ),
            review_required=self.review_required,
            reasons=reasons,
            evidence_digest="digest-1",
        )


def _planned_event() -> dict[str, object]:
    occurred_at = datetime(2026, 8, 4, tzinfo=UTC).isoformat()
    return {
        "producer_principal": "Huginn",
        "correlation_id": "correlation-1",
        "idempotency_key": "event-1",
        "event_type": "public_network_enabled",
        "resource_id": "resource-1",
        "normalized_change": {
            "id": "change-1",
            "correlation_id": "correlation-1",
            "intent_kind": "planned",
            "target_ref": "resource-1",
            "occurred_at": occurred_at,
        },
    }


async def test_forseti_lowers_planned_change_to_human_review() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    assessor = _ChangeAssessor(review_required=True)
    forseti = Forseti(bus=bus, change_assessor=assessor)

    await forseti.on_typed_message("object.event", _planned_event())

    verdict = bus.messages_on("object.verdict")[-1].payload
    assert verdict["risk_verdict"] == "hil"
    assert verdict["change_assessment_status"] == "review"
    assert verdict["change_assessment"]["review_required"] is True
    assert assessor.graph_fresh_values == [False]


async def test_forseti_holds_planned_change_without_assessor() -> None:
    bus = InMemoryBus(registry=load_pantheon())

    await Forseti(bus=bus).on_typed_message("object.event", _planned_event())

    verdict = bus.messages_on("object.verdict")[-1].payload
    assert verdict["risk_verdict"] == "hil"
    assert verdict["change_assessment_status"] == "unavailable"
