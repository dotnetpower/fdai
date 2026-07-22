from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from fdai.core.stewardship.handover_bootstrap import (
    DraftOutcome,
    HandoverBootstrapper,
    PersonRef,
    StewardMapDraft,
)
from fdai.delivery.ingestion_gateway.handover import (
    HandoverBootstrapConsumer,
    HandoverDraftArtifact,
    StateStoreHandoverDraftStore,
)
from fdai.shared.contracts import (
    AccessDescriptor,
    DocumentEnvelope,
    DocumentPurpose,
    DocumentState,
    ProtectionState,
    RetentionPolicy,
    SourceStorageMode,
    StructuralUnit,
    UploadSession,
)
from fdai.shared.providers import DocumentNotFoundError
from fdai.shared.providers.testing.state_store import InMemoryStateStore


async def test_state_store_handover_draft_round_trips_across_instances() -> None:
    state = InMemoryStateStore()
    upload_id = uuid4()
    artifact = HandoverDraftArtifact(
        upload_id=upload_id,
        document_id=uuid4(),
        version_id=uuid4(),
        draft=StewardMapDraft(
            version=1,
            outcome=DraftOutcome.DRAFTED,
            unresolved_people=(PersonRef("Example Operator"),),
            unmapped_agents=("Odin",),
            warnings=("unresolved_people:1",),
        ),
        yaml="stewardship:\n  version: 1\n",
    )

    await StateStoreHandoverDraftStore(state_store=state).put(artifact)
    restored = await StateStoreHandoverDraftStore(state_store=state).get(upload_id)

    assert restored == artifact


async def test_state_store_handover_draft_missing_is_explicit() -> None:
    store = StateStoreHandoverDraftStore(state_store=InMemoryStateStore())

    with pytest.raises(DocumentNotFoundError):
        await store.get(uuid4())


async def test_consumer_proposes_stored_draft_with_authenticated_actor() -> None:
    class Governance:
        def __init__(self) -> None:
            self.calls = []

        async def propose(self, *, artifact, actor_oid):
            self.calls.append((artifact, actor_oid))

    now = datetime.now(tz=UTC)
    upload_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    session = UploadSession(
        upload_id=upload_id,
        document_id=document_id,
        version_id=version_id,
        actor_id="operator-1",
        source_name="handover.txt",
        collection_id="shared",
        object_key="object",
        media_type_hint="text/plain",
        expected_size=10,
        expected_sha256="0" * 64,
        state=DocumentState.INDEXING,
        storage_mode=SourceStorageMode.MANAGED_COPY,
        purposes=(DocumentPurpose.HANDOVER_BOOTSTRAP,),
        access=AccessDescriptor(reference="collection:shared", collection_id="shared"),
        retention=RetentionPolicy(policy_version="v1"),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    envelope = DocumentEnvelope(
        document_id=document_id,
        version_id=version_id,
        source_sha256="0" * 64,
        media_type="text/plain",
        observed_format="text",
        size_bytes=10,
        collection_id="shared",
        purposes=(DocumentPurpose.HANDOVER_BOOTSTRAP,),
        protection_state=ProtectionState.NONE,
        access_descriptor_ref="collection:shared",
        units=(StructuralUnit(unit_id="1", kind="text", locator="L1", text="unknown"),),
        extractor_name="test",
        extractor_version="1",
    )
    governance = Governance()
    store = StateStoreHandoverDraftStore(state_store=InMemoryStateStore())
    consumer = HandoverBootstrapConsumer(
        bootstrapper=HandoverBootstrapper(),
        store=store,
        governance=governance,
    )

    await consumer.consume(session=session, envelope=envelope)

    assert governance.calls[0][1] == "operator-1"
    assert governance.calls[0][0] == await store.get(upload_id)
