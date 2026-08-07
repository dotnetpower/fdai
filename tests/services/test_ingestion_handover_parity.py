"""Focused parity tests for worker-owned stewardship draft generation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fdai_document_worker_service.handover import (
    HandoverBootstrapConsumer,
    HandoverGenerationBudget,
    stewardship_input_from_environment,
)
from fdai_service_contracts import (
    AccessDescriptor,
    DocumentEnvelope,
    DocumentPurpose,
    DocumentState,
    HandoverDraftArtifact,
    ProtectionState,
    ResolvedStewardIdentity,
    RetentionPolicy,
    SourceStorageMode,
    StewardDuty,
    StewardKind,
    StewardResponsibility,
    StewardshipAgentInput,
    StewardshipInput,
    StewardshipSubject,
    StructuralUnit,
    UploadSession,
)


class Directory:
    async def resolve(self, display_name: str) -> ResolvedStewardIdentity | None:
        if display_name == "Jane Kim":
            return ResolvedStewardIdentity(oid="user-jane", kind=StewardKind.USER)
        return None


class Store:
    def __init__(self) -> None:
        self.artifact: HandoverDraftArtifact | None = None

    async def put(self, artifact: HandoverDraftArtifact) -> None:
        self.artifact = artifact


async def test_handover_consumer_generates_grounded_review_only_draft() -> None:
    now = datetime.now(UTC)
    upload_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    session = UploadSession(
        upload_id=upload_id,
        document_id=document_id,
        version_id=version_id,
        actor_id="operator",
        source_name="raci.txt",
        collection_id="shared",
        object_key="source",
        media_type_hint="text/plain",
        expected_size=1,
        expected_sha256="0" * 64,
        state=DocumentState.INDEXING,
        storage_mode=SourceStorageMode.MANAGED_COPY,
        purposes=(DocumentPurpose.HANDOVER_BOOTSTRAP,),
        access=AccessDescriptor(reference="collection:shared", collection_id="shared"),
        retention=RetentionPolicy(policy_version="test"),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    envelope = DocumentEnvelope(
        document_id=document_id,
        version_id=version_id,
        source_sha256="0" * 64,
        media_type="text/plain",
        observed_format="text",
        size_bytes=1,
        collection_id="shared",
        purposes=session.purposes,
        protection_state=ProtectionState.NONE,
        access_descriptor_ref="collection:shared",
        units=(
            StructuralUnit(
                unit_id="line-1",
                kind="paragraph",
                locator="paragraph:1",
                text="Cost governance owner: Jane Kim is accountable for spend.",
            ),
            StructuralUnit(
                unit_id="line-2",
                kind="paragraph",
                locator="paragraph:2",
                text="Chaos engineering owner: Sam Lee.",
            ),
        ),
        extractor_name="test",
        extractor_version="1",
    )
    store = Store()

    warnings = await HandoverBootstrapConsumer(
        directory=Directory(), store=store, stewardship=_stewardship_input()
    ).consume(
        session=session,
        envelope=envelope,
    )

    assert store.artifact is not None
    by_agent = {item.agent_name: item for item in store.artifact.draft.mappings}
    assert by_agent["Njord"].person.oid == "user-jane"
    assert by_agent["Loki"].person.unresolved is True
    assert by_agent["Njord"].citations[0].quote.startswith("Cost governance")
    assert "Jane Kim" in store.artifact.yaml
    assert "user-jane" in store.artifact.yaml
    assert "existing-njord" in store.artifact.yaml
    assert 'oid: "maintainer-1"' in store.artifact.yaml
    assert "accept_autonomous" not in store.artifact.yaml
    assert "review" in store.artifact.yaml.casefold()
    assert any("did not resolve" in warning for warning in warnings)


async def test_handover_consumer_abstains_on_unknown_agent_or_ungrounded_text() -> None:
    now = datetime.now(UTC)
    upload_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    session = UploadSession(
        upload_id=upload_id,
        document_id=document_id,
        version_id=version_id,
        actor_id="operator",
        source_name="handover.txt",
        collection_id="shared",
        object_key="source",
        media_type_hint="text/plain",
        expected_size=1,
        expected_sha256="0" * 64,
        state=DocumentState.INDEXING,
        storage_mode=SourceStorageMode.MANAGED_COPY,
        purposes=(DocumentPurpose.HANDOVER_BOOTSTRAP,),
        access=AccessDescriptor(reference="collection:shared", collection_id="shared"),
        retention=RetentionPolicy(policy_version="test"),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    envelope = DocumentEnvelope(
        document_id=document_id,
        version_id=version_id,
        source_sha256="0" * 64,
        media_type="text/plain",
        observed_format="text",
        size_bytes=1,
        collection_id="shared",
        purposes=session.purposes,
        protection_state=ProtectionState.NONE,
        access_descriptor_ref="collection:shared",
        units=(
            StructuralUnit(
                unit_id="line-1",
                kind="paragraph",
                locator="paragraph:1",
                text="Team offsite next Friday.",
            ),
        ),
        extractor_name="test",
        extractor_version="1",
    )
    store = Store()

    warnings = await HandoverBootstrapConsumer(
        directory=Directory(), store=store, stewardship=_stewardship_input()
    ).consume(
        session=session,
        envelope=envelope,
    )

    assert store.artifact is not None
    assert store.artifact.draft.outcome.value == "abstained"
    assert store.artifact.draft.mappings == ()
    assert any("nothing was drafted" in warning for warning in warnings)


async def test_handover_consumer_abstains_before_directory_io_when_budget_is_exceeded() -> None:
    class UnexpectedDirectory:
        async def resolve(self, _display_name: str) -> ResolvedStewardIdentity | None:
            raise AssertionError("directory lookup must not run after a source budget failure")

    session, envelope = _session_and_envelope(
        "agent: Njord; responsibility: accountable; subject: user; identity: Jane Kim\n"
        "agent: Loki; responsibility: informed; subject: user; identity: Jane Kim"
    )
    store = Store()

    warnings = await HandoverBootstrapConsumer(
        directory=UnexpectedDirectory(),
        store=store,
        stewardship=_stewardship_input(),
        budget=HandoverGenerationBudget(max_lines=1),
    ).consume(session=session, envelope=envelope)

    assert store.artifact is not None
    assert store.artifact.draft.outcome.value == "abstained"
    assert warnings == ("handover source line budget exceeded", "nothing was drafted")


def test_service_owned_stewardship_input_is_bounded_and_versioned() -> None:
    snapshot = stewardship_input_from_environment(
        {
            "FDAI_STEWARDSHIP_VERSION": "2",
            "FDAI_MAINTAINERS": "maintainer-1,maintainer-2",
            "FDAI_STEWARD_NJORD": "user:existing-njord:accountable:primary",
        }
    )

    assert snapshot is not None
    assert snapshot.version == 2
    assert len(snapshot.revision) == 16
    njord = next(item for item in snapshot.agents if item.agent_name == "Njord")
    assert njord.stewards[0].duty is StewardDuty.PRIMARY


def _stewardship_input() -> StewardshipInput:
    return StewardshipInput(
        version=2,
        revision="revision-1",
        maintainers=("maintainer-1",),
        agents=(
            StewardshipAgentInput(
                agent_name="Njord",
                stewards=(
                    StewardshipSubject(
                        kind=StewardKind.USER,
                        oid="existing-njord",
                        responsibility=StewardResponsibility.ACCOUNTABLE,
                        duty=StewardDuty.PRIMARY,
                    ),
                ),
            ),
        ),
    )


def _session_and_envelope(text: str) -> tuple[UploadSession, DocumentEnvelope]:
    now = datetime.now(UTC)
    document_id = uuid4()
    version_id = uuid4()
    session = UploadSession(
        upload_id=uuid4(),
        document_id=document_id,
        version_id=version_id,
        actor_id="operator",
        source_name="handover.txt",
        collection_id="shared",
        object_key="source",
        media_type_hint="text/plain",
        expected_size=1,
        expected_sha256="0" * 64,
        state=DocumentState.INDEXING,
        storage_mode=SourceStorageMode.MANAGED_COPY,
        purposes=(DocumentPurpose.HANDOVER_BOOTSTRAP,),
        access=AccessDescriptor(reference="collection:shared", collection_id="shared"),
        retention=RetentionPolicy(policy_version="test"),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    return session, DocumentEnvelope(
        document_id=document_id,
        version_id=version_id,
        source_sha256="0" * 64,
        media_type="text/plain",
        observed_format="text",
        size_bytes=len(text),
        collection_id="shared",
        purposes=session.purposes,
        protection_state=ProtectionState.NONE,
        access_descriptor_ref="collection:shared",
        units=(StructuralUnit(unit_id="line-1", kind="paragraph", locator="line:1", text=text),),
        extractor_name="test",
        extractor_version="1",
    )
