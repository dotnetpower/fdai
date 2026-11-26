"""Audited connector checkpoints preserve identity and replay boundaries."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.kubernetes_connector import (
    ConnectorAdmissionError,
    ConnectorAdmissionStatus,
    ConnectorEvidenceInbox,
)
from fdai.shared.providers.testing import InMemoryStateStore
from fdai_service_contracts.cluster_connector import ConnectorEvidence, ConnectorRegistration

NOW = datetime(2026, 9, 19, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


def registration(**changes: object) -> ConnectorRegistration:
    return ConnectorRegistration.model_validate(
        {
            "scope": {
                "deployment_ref": "deployment-example",
                "cluster_ref": "cluster-example",
                "connector_id": "connector-example",
                "enrollment_revision": 1,
            },
            "principal_ref": "principal-example",
            "role": "observer",
            "namespaces": ["example"],
            "capabilities": ["inventory.snapshot"],
            "valid_from": NOW - timedelta(minutes=5),
            "expires_at": NOW + timedelta(hours=1),
            **changes,
        }
    )


def packet(**changes: object) -> ConnectorEvidence:
    return ConnectorEvidence.model_validate(
        {
            "scope": registration().scope,
            "capability": "inventory.snapshot",
            "stream_id": "stream-example",
            "sequence": 1,
            "observed_at": NOW,
            "producer_revision": DIGEST,
            "artifact_digest": DIGEST,
            "artifact_bytes": 100,
            "namespaces": ["example"],
            "complete": True,
            **changes,
        }
    )


async def admit(inbox: ConnectorEvidenceInbox, value: ConnectorEvidence):
    return await inbox.accept(
        value, registration=registration(), principal_ref="principal-example", now=NOW
    )


async def test_replay_and_restart_preserve_checkpoint() -> None:
    store = InMemoryStateStore()
    first = await admit(ConnectorEvidenceInbox(store), packet())
    assert first.status == ConnectorAdmissionStatus.ACCEPTED
    retry = await admit(ConnectorEvidenceInbox(store), packet())
    assert retry.status == ConnectorAdmissionStatus.DUPLICATE
    assert retry.evidence_digest == first.evidence_digest
    next_packet = packet(sequence=2)
    assert (await admit(ConnectorEvidenceInbox(store), next_packet)).sequence == 2


async def test_concurrent_identical_delivery_has_one_winner() -> None:
    inbox = ConnectorEvidenceInbox(InMemoryStateStore())
    outcomes = await asyncio.gather(*(admit(inbox, packet()) for _ in range(12)))
    assert sum(result.status == ConnectorAdmissionStatus.ACCEPTED for result in outcomes) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"sequence": 3},
        {"artifact_digest": "sha256:" + "b" * 64},
        {"sequence": 2, "observed_at": NOW - timedelta(seconds=1)},
    ],
)
async def test_collision_gap_and_regressed_time_do_not_advance(changes: dict[str, object]) -> None:
    inbox = ConnectorEvidenceInbox(InMemoryStateStore())
    await admit(inbox, packet())
    with pytest.raises(ConnectorAdmissionError):
        await admit(inbox, packet(**changes))
    assert (await admit(inbox, packet())).status == ConnectorAdmissionStatus.DUPLICATE


async def test_replay_does_not_bypass_revocation() -> None:
    inbox = ConnectorEvidenceInbox(InMemoryStateStore())
    await admit(inbox, packet())
    with pytest.raises(ValueError):
        await inbox.accept(
            packet(),
            registration=registration(revoked=True),
            principal_ref="principal-example",
            now=NOW,
        )


async def test_model_copy_cannot_bypass_validation() -> None:
    inbox = ConnectorEvidenceInbox(InMemoryStateStore())
    with pytest.raises(ValueError):
        await admit(inbox, packet().model_copy(update={"execution_authority": True}))


async def test_first_delivery_requires_sequence_one() -> None:
    with pytest.raises(ConnectorAdmissionError):
        await admit(ConnectorEvidenceInbox(InMemoryStateStore()), packet(sequence=2))


async def test_forced_create_race_preserves_one_audit_and_exact_duplicate() -> None:
    class RacingStore(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.readers = 0
            self.ready = asyncio.Event()

        async def read_state(self, key):
            previous = await super().read_state(key)
            if self.readers < 2:
                self.readers += 1
                if self.readers == 2:
                    self.ready.set()
                await self.ready.wait()
            return previous

    store = RacingStore()
    outcomes = await asyncio.gather(
        admit(ConnectorEvidenceInbox(store), packet()),
        admit(ConnectorEvidenceInbox(store), packet()),
    )
    assert sorted(result.status.value for result in outcomes) == ["accepted", "duplicate"]
    assert len(list(store.audit_entries)) == 1


async def test_store_failure_does_not_report_acceptance() -> None:
    class FailingStore(InMemoryStateStore):
        async def write_state_with_audit_if_absent(self, key, value, audit_entry):
            raise RuntimeError("synthetic storage failure")

    store = FailingStore()
    with pytest.raises(RuntimeError, match="synthetic storage failure"):
        await admit(ConnectorEvidenceInbox(store), packet())
    assert list(store.audit_entries) == []


async def test_equal_sequence_different_content_never_adds_an_audit() -> None:
    store = InMemoryStateStore()
    inbox = ConnectorEvidenceInbox(store)
    await admit(inbox, packet())
    with pytest.raises(ConnectorAdmissionError):
        await admit(inbox, packet(artifact_bytes=101))
    assert len(list(store.audit_entries)) == 1
