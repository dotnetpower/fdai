from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from fdai.core.human_assignment import AssignmentCaseService, AssignmentOwnershipCoordinator
from fdai.core.stewardship import load_stewardship_from_yaml
from fdai.runtime.stewardship_merge_effects import StewardshipMergeEffectsWorker
from fdai.shared.providers.notifications import NotificationMessage
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.remediation_pr import RecordingRemediationPrPublisher
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.handover import StewardshipMergeRecord

_CONFIG = Path(__file__).resolve().parents[4] / "config" / "agent-stewardship.yaml"


@dataclass
class RecordingNotifications:
    messages: list[NotificationMessage]

    async def dispatch(self, message: NotificationMessage):
        self.messages.append(message)
        return SimpleNamespace(outcome=SimpleNamespace(value="delivered_all"))


def _merge(delivery_id: str = "delivery-1") -> StewardshipMergeRecord:
    yaml = _CONFIG.read_text(encoding="utf-8").replace(
        "00000000-0000-0000-0000-000000000000",
        "00000000-0000-0000-0000-000000000001",
    )
    return StewardshipMergeRecord(
        delivery_id=delivery_id,
        pr_ref="dotnetpower/fdai#1",
        actor_identity="github:reviewer",
        merge_commit_sha="a" * 40,
        merged_yaml=yaml,
    )


async def test_merge_effects_notify_and_audit_once() -> None:
    store = InMemoryStateStore()
    merge = _merge()
    await store.write_state(f"stewardship_merge:{merge.delivery_id}", merge.model_dump(mode="json"))
    notifications = RecordingNotifications([])
    worker = StewardshipMergeEffectsWorker(
        store=store,
        base=load_stewardship_from_yaml(_CONFIG),
        notifications=notifications,
    )

    assert await worker.run_once() == 1
    assert await worker.run_once() == 0

    assert len(notifications.messages) == 1
    message = notifications.messages[0]
    assert message.correlation_id == merge.delivery_id
    assert message.metadata["steward_oids"] == "00000000-0000-0000-0000-000000000001"
    receipt = await store.read_state(f"stewardship_merge_effect:{merge.delivery_id}")
    assert receipt is not None
    assert receipt["recipient_count"] == 1
    assert len(receipt["affected_agents"]) == 15
    assert len(store.audit_entries) == 1


async def test_invalid_merge_is_quarantined_without_blocking_later_record() -> None:
    store = InMemoryStateStore()
    invalid = _merge("invalid").model_copy(update={"merged_yaml": "stewardship:\n  version: 2"})
    valid = _merge("valid")
    await store.write_state("stewardship_merge:invalid", invalid.model_dump(mode="json"))
    await store.write_state("stewardship_merge:valid", valid.model_dump(mode="json"))
    notifications = RecordingNotifications([])
    worker = StewardshipMergeEffectsWorker(
        store=store,
        base=load_stewardship_from_yaml(_CONFIG),
        notifications=notifications,
    )

    assert await worker.run_once() == 2
    assert await worker.run_once() == 0
    failures = await store.read_states("stewardship_merge_effect_failure:", limit=10)
    assert failures[0]["failure_kind"] == "invalid_merged_stewardship"
    assert len(notifications.messages) == 1


async def test_merge_worker_pages_past_processed_newer_records() -> None:
    store = InMemoryStateStore()
    notifications = RecordingNotifications([])
    worker = StewardshipMergeEffectsWorker(
        store=store,
        base=load_stewardship_from_yaml(_CONFIG),
        notifications=notifications,
        batch_limit=2,
    )
    for index in range(5):
        merge = _merge(f"delivery-{index}")
        await store.write_state(
            f"stewardship_merge:{merge.delivery_id}",
            merge.model_dump(mode="json"),
        )

    assert await worker.run_once() == 2
    assert await worker.run_once() == 2
    assert await worker.run_once() == 1
    assert await worker.run_once() == 0
    assert len(notifications.messages) == 5


async def test_malformed_matching_assignment_is_quarantined_after_one_notification() -> None:
    store = InMemoryStateStore()
    merge = _merge()
    await store.write_state(f"stewardship_merge:{merge.delivery_id}", merge.model_dump(mode="json"))
    await store.write_state(
        "human_assignment:ownership-proposal:malformed",
        {
            "pr_ref": merge.pr_ref,
            "candidate_digest": "a" * 64,
            "opened_at": "2026-09-05T08:00:00+00:00",
        },
    )
    notifications = RecordingNotifications([])
    worker = StewardshipMergeEffectsWorker(
        store=store,
        base=load_stewardship_from_yaml(_CONFIG),
        notifications=notifications,
        ownership=AssignmentOwnershipCoordinator(
            cases=AssignmentCaseService(store),
            store=store,
            pr_publisher=RecordingRemediationPrPublisher(),
            event_bus=InMemoryEventBus(),
            event_topic="fdai.events",
        ),
    )

    assert await worker.run_once() == 1
    assert await worker.run_once() == 0
    assert len(notifications.messages) == 1
    failures = await store.read_states("stewardship_merge_effect_failure:", limit=10)
    assert failures[0]["failure_kind"] == "assignment_merge_mismatch"
