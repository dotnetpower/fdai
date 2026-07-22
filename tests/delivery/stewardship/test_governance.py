from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import yaml

from fdai.core.stewardship import load_stewardship_from_mapping, load_stewardship_from_yaml
from fdai.core.stewardship.handover_bootstrap import DraftOutcome, StewardMapDraft
from fdai.delivery.ingestion_gateway.handover import HandoverDraftArtifact
from fdai.delivery.stewardship import StewardshipGovernanceService, StewardshipMerge
from fdai.shared.providers.testing import InMemoryStateStore
from fdai.shared.providers.testing.remediation_pr import RecordingRemediationPrPublisher

_CONFIG = Path(__file__).resolve().parents[3] / "config" / "agent-stewardship.yaml"


class RecordingNotifications:
    def __init__(self) -> None:
        self.messages = []

    async def dispatch(self, message):
        self.messages.append(message)
        return object()


def _artifact() -> HandoverDraftArtifact:
    return HandoverDraftArtifact(
        upload_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        draft=StewardMapDraft(version=1, outcome=DraftOutcome.DRAFTED),
        yaml=_CONFIG.read_text(encoding="utf-8"),
    )


async def test_proposal_is_idempotent_and_audited() -> None:
    publisher = RecordingRemediationPrPublisher()
    notifications = RecordingNotifications()
    store = InMemoryStateStore()
    service = StewardshipGovernanceService(
        current_map=load_stewardship_from_yaml(_CONFIG),
        publisher=publisher,
        notifications=notifications,
        state_store=store,
    )
    artifact = _artifact()

    first = await service.propose(artifact=artifact, actor_oid="operator-1")
    second = await service.propose(artifact=artifact, actor_oid="operator-1")

    assert first.pr_ref == second.pr_ref
    assert second.already_existed is True
    assert len(publisher.records) == 1
    assert publisher.records[0].patch_path == "config/agent-stewardship.yaml"
    proposed = load_stewardship_from_mapping(
        yaml.safe_load(publisher.records[0].patch),
        environ={},
    )
    assert proposed == load_stewardship_from_yaml(_CONFIG)
    assert len(notifications.messages) == 1
    assert len(store.audit_entries) == 1

    replacement_publisher = RecordingRemediationPrPublisher()
    restarted = StewardshipGovernanceService(
        current_map=load_stewardship_from_yaml(_CONFIG),
        publisher=replacement_publisher,
        notifications=notifications,
        state_store=store,
    )
    recovered = await restarted.propose(artifact=artifact, actor_oid="operator-1")
    assert recovered.pr_ref == first.pr_ref
    assert recovered.already_existed is True
    assert replacement_publisher.records == ()


async def test_merge_delivery_is_idempotent_and_audited() -> None:
    notifications = RecordingNotifications()
    store = InMemoryStateStore()
    service = StewardshipGovernanceService(
        current_map=load_stewardship_from_yaml(_CONFIG),
        publisher=RecordingRemediationPrPublisher(),
        notifications=notifications,
        state_store=store,
    )
    merge = StewardshipMerge(
        delivery_id="delivery-1",
        pr_ref="acme/fdai#42",
        actor_identity="github:operator",
        merged_yaml=_CONFIG.read_text(encoding="utf-8"),
    )

    assert await service.record_merge(merge) is True
    assert await service.record_merge(merge) is False
    assert len(notifications.messages) == 1
    assert "merged" in notifications.messages[0].title
    assert len(store.audit_entries) == 1
