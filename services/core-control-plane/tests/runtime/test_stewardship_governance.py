"""Restart and replay coverage for stewardship governance delivery."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fdai.core.stewardship.governance import StewardshipGovernanceService
from fdai.runtime.stewardship_governance import (
    StewardshipGovernanceWorker,
    build_stewardship_governance_worker,
)
from fdai.shared.providers.testing.remediation_pr import RecordingRemediationPrPublisher
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.handover import (
    HandoverDraftArtifact,
    HandoverDraftOutcome,
    HandoverMapping,
    HandoverPerson,
    HandoverSourceSpan,
    StewardResponsibility,
    StewardshipDraft,
)

_CONFIG = Path(__file__).resolve().parents[4] / "config" / "agent-stewardship.yaml"


def _artifact(
    *,
    upload_id: int = 1,
    outcome: HandoverDraftOutcome = HandoverDraftOutcome.DRAFTED,
) -> HandoverDraftArtifact:
    mapping = HandoverMapping(
        agent_name="Freyr",
        person=HandoverPerson(display_name="Steward Example", oid="oid-example"),
        responsibility=StewardResponsibility.ACCOUNTABLE,
        confidence=0.9,
        citations=(HandoverSourceSpan(doc_id="doc-1", line=1, quote="Freyr steward"),),
    )
    return HandoverDraftArtifact(
        upload_id=UUID(int=upload_id, version=4),
        document_id=UUID(int=2, version=4),
        version_id=UUID(int=3, version=4),
        draft=StewardshipDraft(
            outcome=outcome,
            mappings=(mapping,) if outcome is HandoverDraftOutcome.DRAFTED else (),
        ),
        yaml=_CONFIG.read_text(encoding="utf-8"),
    )


async def _store_artifact(
    store: InMemoryStateStore,
    artifact: HandoverDraftArtifact,
) -> None:
    await store.write_state(
        f"handover_draft:{artifact.upload_id}",
        artifact.model_dump(mode="json"),
    )


def test_artifact_projection_excludes_output_only_computed_fields() -> None:
    payload = _artifact().to_dict()

    draft = payload["draft"]
    assert isinstance(draft, dict)
    mappings = draft["mappings"]
    assert isinstance(mappings, list)
    mapping = mappings[0]
    assert isinstance(mapping, dict)
    person = mapping["person"]
    assert isinstance(person, dict)
    assert "unresolved" not in person
    assert HandoverDraftArtifact.model_validate(payload).upload_id == _artifact().upload_id


async def test_worker_publishes_and_audits_one_candidate_once() -> None:
    store = InMemoryStateStore()
    publisher = RecordingRemediationPrPublisher()
    artifact = _artifact()
    await _store_artifact(store, artifact)
    worker = StewardshipGovernanceWorker(
        store=store,
        governance=StewardshipGovernanceService(publisher=publisher),
    )

    assert await worker.run_once() == 1
    assert await worker.run_once() == 0

    assert len(publisher.records) == 1
    receipts = await store.read_states("stewardship_governance:", limit=10)
    assert len(receipts) == 1
    assert receipts[0]["pr_ref"] == "pr-1"
    assert receipts[0]["published"] is True
    assert receipts[0]["replayed"] is False
    assert len(store.audit_entries) == 1


async def test_worker_records_abstention_without_opening_pr() -> None:
    store = InMemoryStateStore()
    publisher = RecordingRemediationPrPublisher()
    artifact = _artifact(outcome=HandoverDraftOutcome.ABSTAINED)
    await _store_artifact(store, artifact)
    worker = StewardshipGovernanceWorker(
        store=store,
        governance=StewardshipGovernanceService(publisher=publisher),
    )

    assert await worker.run_once() == 1

    (receipt,) = await store.read_states("stewardship_governance:", limit=10)
    assert receipt["published"] is False
    assert receipt["reason"] == "abstained_draft"
    assert publisher.records == ()


async def test_invalid_candidate_is_rejected_without_blocking_valid_work() -> None:
    store = InMemoryStateStore()
    publisher = RecordingRemediationPrPublisher()
    artifact = _artifact().model_copy(update={"yaml": "stewardship:\n  version: 2\n"})
    await _store_artifact(store, artifact)
    worker = StewardshipGovernanceWorker(
        store=store,
        governance=StewardshipGovernanceService(publisher=publisher),
    )

    valid = _artifact(upload_id=4)
    await _store_artifact(store, valid)

    assert await worker.run_once() == 2
    assert await worker.run_once() == 0

    (receipt,) = await store.read_states("stewardship_governance:", limit=10)
    assert receipt["upload_id"] == str(valid.upload_id)
    (failure,) = await store.read_states("stewardship_governance_failure:", limit=10)
    assert failure["upload_id"] == str(artifact.upload_id)
    assert failure["failure_kind"] == "invalid_candidate"
    assert len(publisher.records) == 1


async def test_worker_pages_past_processed_newer_drafts() -> None:
    store = InMemoryStateStore()
    publisher = RecordingRemediationPrPublisher()
    worker = StewardshipGovernanceWorker(
        store=store,
        governance=StewardshipGovernanceService(publisher=publisher),
        batch_limit=2,
    )
    artifacts = tuple(_artifact(upload_id=index) for index in range(1, 6))
    for artifact in artifacts:
        await _store_artifact(store, artifact)

    assert await worker.run_once() == 2
    assert await worker.run_once() == 2
    assert await worker.run_once() == 1
    assert await worker.run_once() == 0

    assert len(publisher.records) == 5
    receipts = await store.read_states("stewardship_governance:", limit=10)
    assert {receipt["upload_id"] for receipt in receipts} == {
        str(artifact.upload_id) for artifact in artifacts
    }


def test_builder_requires_durable_store_for_configured_gitops() -> None:
    store = InMemoryStateStore()
    publisher = RecordingRemediationPrPublisher()

    assert (
        build_stewardship_governance_worker(
            store=store,
            publisher=publisher,
            environment={},
        )
        is None
    )
    with pytest.raises(RuntimeError, match="requires FDAI_STATE_STORE_DSN"):
        build_stewardship_governance_worker(
            store=store,
            publisher=publisher,
            environment={"FDAI_GITOPS_TOKEN": "configured"},
        )
    with pytest.raises(RuntimeError, match="requires FDAI_STATE_STORE_DSN"):
        build_stewardship_governance_worker(
            store=store,
            publisher=publisher,
            environment={
                "FDAI_GITHUB_APP_CLIENT_ID": "Iv1.example",
                "FDAI_GITHUB_APP_INSTALLATION_ID": "123",
                "FDAI_GITHUB_APP_PRIVATE_KEY": "configured",
            },
        )


def test_builder_validates_bounds_and_can_be_disabled() -> None:
    store = InMemoryStateStore()
    publisher = RecordingRemediationPrPublisher()
    base = {
        "FDAI_GITOPS_TOKEN": "configured",
        "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
    }

    assert (
        build_stewardship_governance_worker(
            store=store,
            publisher=publisher,
            environment={**base, "FDAI_STEWARDSHIP_GOVERNANCE_ENABLED": "false"},
        )
        is None
    )
    with pytest.raises(RuntimeError, match="BATCH_LIMIT MUST be between"):
        build_stewardship_governance_worker(
            store=store,
            publisher=publisher,
            environment={**base, "FDAI_STEWARDSHIP_GOVERNANCE_BATCH_LIMIT": "0"},
        )
