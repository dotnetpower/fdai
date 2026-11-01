"""Focused parity tests for worker-owned stewardship draft generation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fdai_document_worker_service.adapters import handover as handover_store_module
from fdai_document_worker_service.adapters.handover_model import (
    AzureReviewedHandoverInterpreter,
    HandoverModelTarget,
    HandoverStructuredResponse,
)
from fdai_document_worker_service.adapters.handover_model_configuration import (
    build_handover_interpreter,
)
from fdai_document_worker_service.handover import (
    HandoverBootstrapConsumer,
    HandoverGenerationBudget,
    _extract_line,
    stewardship_input_from_environment,
)
from fdai_document_worker_service.handover_interpretation import (
    ReviewedHandoverInterpretation,
    handover_proposal_digest,
)
from fdai_service_contracts import (
    AccessDescriptor,
    DocumentEnvelope,
    DocumentPurpose,
    DocumentState,
    HandoverDraftArtifact,
    HandoverMapping,
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
from fdai_service_contracts.handover import HandoverModelReview
from pydantic import ValidationError


async def test_handover_model_call_reservation_and_usage_never_reset(monkeypatch) -> None:
    rows = [("reserved",), None, ("usage",), None]
    statements: list[str] = []

    class Cursor:
        async def fetchone(self):
            return rows.pop(0)

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, statement: str, values):
            statements.append(statement)
            return Cursor()

    async def connect(*args, **kwargs):
        return Connection()

    monkeypatch.setattr(handover_store_module.psycopg.AsyncConnection, "connect", connect)
    store = handover_store_module.PostgresHandoverDraftStore(dsn="synthetic-test-dsn")
    document_id, version_id = uuid4(), uuid4()
    reservation = dict(document_id=document_id, version_id=version_id, source_sha256="a" * 64)
    assert await store.reserve_model_calls(**reservation) is True
    assert await store.reserve_model_calls(**reservation) is False
    usage = dict(
        document_id=document_id,
        version_id=version_id,
        stage="author",
        prompt_tokens=12,
        completion_tokens=3,
        cost_micros=1,
        pricing_sha256="b" * 64,
    )
    await store.record_model_usage(**usage)
    with pytest.raises(ValueError, match="cannot replace"):
        await store.record_model_usage(**usage)
    assert all("DO NOTHING" in statement for statement in statements[:2])
    assert all("AND NOT" in statement for statement in statements[2:])


async def test_handover_model_transport_rejects_malformed_json_but_retains_measured_usage() -> None:
    class Credential:
        async def get_token(self, scope: str):
            assert scope == "https://cognitiveservices.azure.com/.default"
            return SimpleNamespace(token="synthetic-test-token")

    async def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(
            200,
            json={
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
                "choices": [{"finish_reason": "stop", "message": {"content": "not-json"}}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        interpreter = AzureReviewedHandoverInterpreter(
            author=HandoverModelTarget(
                "https://author.example.invalid", "author", "first", "first-family"
            ),
            reviewer=HandoverModelTarget(
                "https://reviewer.example.invalid", "reviewer", "second", "second-family"
            ),
            credential=Credential(),
            client=client,
            reservations=None,
            author_prompt="Ground exact source mappings.",
            reviewer_prompt="Verify every source mapping.",
        )
        result = await interpreter._complete(
            interpreter._author, "Ground mappings.", {}, {"type": "object"}
        )
        assert result is not None and result.proposal is None
        assert result.prompt_tokens == 12 and result.completion_tokens == 3


def test_adaptive_handover_factory_defaults_closed_and_requires_reviewed_targets(tmp_path) -> None:
    assert (
        build_handover_interpreter(environment={}, credential=None, client=None, store=None) is None
    )
    prompt = tmp_path / "reviewed-handover.txt"
    prompt.write_text(
        "Ground mappings in exact document spans. Never grant authority.", encoding="utf-8"
    )
    digest = hashlib.sha256(prompt.read_bytes()).hexdigest()
    target = {
        "endpoint": "https://model.example.invalid",
        "deployment": "model-deployment",
        "publisher": "publisher-one",
        "family": "family-one",
        "input_micros_per_million": 1_000_000,
        "output_micros_per_million": 2_000_000,
    }
    config = {
        "author": target,
        "reviewer": {**target, "publisher": "publisher-two", "family": "family-two"},
        "author_prompt_path": str(prompt),
        "author_prompt_sha256": digest,
        "reviewer_prompt_path": str(prompt),
        "reviewer_prompt_sha256": digest,
    }
    with pytest.raises(ValueError, match="invalid"):
        build_handover_interpreter(
            environment={"FDAI_HANDOVER_MODELS_JSON": json.dumps(config)},
            credential=None,
            client=None,
            store=None,
        )


def test_handover_model_review_rejects_self_review_and_missing_provenance() -> None:
    material = {
        "author_identity": "publisher:author",
        "reviewer_identity": "publisher:reviewer",
        "source_sha256": "a" * 64,
        "proposal_sha256": "b" * 64,
        "reviewed_mapping_count": 1,
    }
    assert HandoverModelReview.model_validate(material).model_calls == 2
    for override in (
        {"reviewer_identity": "publisher:author"},
        {"author_identity": " "},
        {"source_sha256": "unbound"},
        {"reviewed_mapping_count": True},
    ):
        with pytest.raises(ValidationError):
            HandoverModelReview.model_validate({**material, **override})


def test_worker_handover_never_guesses_prose_or_truncates_citations() -> None:
    assert (
        _extract_line("Cost governance owner: Jane Kim is accountable for spend.", "doc-one", 1)
        == ()
    )
    line = "Agent: Njord; responsibility: accountable; subject: user; identity: " + "Name" * 32
    (mapping,) = _extract_line(line, "doc-one", 1)
    assert "".join(span.quote for span in mapping.citations) == line
    assert all(len(span.quote) <= 200 for span in mapping.citations)


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

    async def get(self, upload_id) -> HandoverDraftArtifact | None:
        if self.artifact is not None:
            assert self.artifact.upload_id == upload_id
        return self.artifact


@pytest.mark.parametrize(
    "adaptive,invalid",
    [(False, None), (True, None), (True, "review"), (True, "quote"), (True, "identity")],
)
async def test_handover_consumer_generates_grounded_review_only_draft(
    adaptive: bool, invalid: str | None
) -> None:
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
                text="Agent: Njord; responsibility: accountable; subject: user; identity: Jane Kim",
            ),
            StructuralUnit(
                unit_id="line-2",
                kind="paragraph",
                locator="paragraph:2",
                text="Agent: Loki; responsibility: accountable; subject: user; identity: Sam Lee",
            ),
        ),
        extractor_name="test",
        extractor_version="1",
    )
    store = Store()
    authored: list[HandoverMapping] = []
    if adaptive:
        units = tuple(
            unit.model_copy(update={"text": text})
            for unit, text in zip(
                envelope.units,
                (
                    "Jane Kim is the accountable cost-governance lead.",
                    "Sam Lee leads chaos and resilience testing.",
                ),
                strict=True,
            )
        )
        envelope = envelope.model_copy(update={"units": units})
        for index, (agent, name) in enumerate((("Njord", "Jane Kim"), ("Loki", "Sam Lee"))):
            authored.append(
                HandoverMapping.model_validate(
                    {
                        "agent_name": agent,
                        "person": {"display_name": name},
                        "responsibility": "accountable",
                        "confidence": 0.9,
                        "source": "model",
                        "citations": [
                            {
                                "doc_id": str(document_id),
                                "line": index + 1,
                                "quote": units[index].text,
                            }
                        ],
                    }
                )
            )

    class Interpreter:
        async def interpret(self, source: DocumentEnvelope) -> ReviewedHandoverInterpretation:
            mappings = tuple(authored)
            return ReviewedHandoverInterpretation(
                mappings=mappings,
                review=HandoverModelReview(
                    author_identity="publisher:author",
                    reviewer_identity="other:reviewer",
                    source_sha256=source.source_sha256,
                    proposal_sha256=handover_proposal_digest(mappings),
                    reviewed_mapping_count=len(mappings),
                ),
            )

    if adaptive:

        class Reservation:
            calls = 0

            async def record_model_usage(self, **kwargs: object) -> None:
                assert kwargs["stage"] in {"author", "reviewer"}

            async def reserve_model_calls(self, **kwargs: object) -> bool:
                self.calls += 1
                return self.calls == 1

        class ScriptedModel(AzureReviewedHandoverInterpreter):
            calls = 0

            async def _complete(
                self, target: HandoverModelTarget, prompt: str, payload: dict, schema: dict
            ) -> HandoverStructuredResponse:
                from jsonschema import Draft202012Validator

                self.calls += 1
                if self.calls == 1:
                    output = {
                        "mappings": [
                            mapping.model_dump(mode="json", exclude_computed_fields=True)
                            for mapping in authored
                        ]
                    }
                    if invalid == "quote":
                        output["mappings"][0]["citations"][0]["quote"] = (
                            "Invented source quotation."
                        )
                    if invalid == "identity":
                        output["mappings"][0]["person"]["oid"] = "invented-person-id"
                    Draft202012Validator(schema).validate(output)
                    return HandoverStructuredResponse(output, 100, 40)
                return HandoverStructuredResponse(
                    {
                        "proposal_sha256": payload["proposal_sha256"],
                        "accepted": invalid != "review",
                        "reviewed_mapping_count": len(authored),
                    },
                    80,
                    20,
                )

        interpreter = ScriptedModel(
            author=HandoverModelTarget(
                "https://author.example.invalid", "author", "provider-one", "family-one"
            ),
            reviewer=HandoverModelTarget(
                "https://reviewer.example.invalid", "reviewer", "provider-two", "family-two"
            ),
            credential=None,
            client=None,
            reservations=Reservation(),
            author_prompt="Ground source mappings only.",
            reviewer_prompt="Independently verify every mapping.",
        )
    else:
        interpreter = None

    warnings = await HandoverBootstrapConsumer(
        directory=Directory(),
        store=store,
        stewardship=_stewardship_input(),
        interpreter=interpreter,
    ).consume(
        session=session,
        envelope=envelope,
    )

    assert store.artifact is not None
    if invalid is not None:
        assert store.artifact.draft.outcome.value == "abstained"
        assert store.artifact.draft.mappings == ()
        assert store.artifact.model_review is None
        assert store.artifact.schema_version == "1.0.0"
        assert interpreter.calls == (2 if invalid == "review" else 1)
        return
    by_agent = {item.agent_name: item for item in store.artifact.draft.mappings}
    assert by_agent["Njord"].person.oid == "user-jane"
    assert by_agent["Loki"].person.unresolved is True
    assert (
        by_agent["Njord"].citations[0].quote.startswith("Jane Kim" if adaptive else "Agent: Njord;")
    )
    assert store.artifact.schema_version == ("1.1.0" if adaptive else "1.0.0")
    assert (store.artifact.model_review is not None) is adaptive
    if adaptive:
        serialized = store.artifact.to_dict()
        altered = {
            **serialized,
            "draft": {
                **serialized["draft"],
                "mappings": [
                    {**serialized["draft"]["mappings"][0], "agent_name": "Odin"},
                    serialized["draft"]["mappings"][1],
                ],
            },
        }
        with pytest.raises(ValidationError, match="every exact model mapping"):
            HandoverDraftArtifact.model_validate(altered)
        with pytest.raises(ValidationError, match="version 1.1"):
            HandoverDraftArtifact.model_validate({**serialized, "schema_version": "1.0.0"})
    assert "Jane Kim" in store.artifact.yaml
    assert "user-jane" in store.artifact.yaml
    assert "existing-njord" in store.artifact.yaml
    assert 'oid: "maintainer-1"' in store.artifact.yaml
    assert "accept_autonomous" not in store.artifact.yaml
    assert "review" in store.artifact.yaml.casefold()
    assert any("did not resolve" in warning for warning in warnings)
    if adaptive:
        await HandoverBootstrapConsumer(
            directory=Directory(),
            store=store,
            stewardship=_stewardship_input(),
            interpreter=interpreter,
        ).consume(session=session, envelope=envelope)
        assert interpreter.calls == 2


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


async def test_handover_consumer_falls_back_to_projected_stewardship_and_resolves_known_oids() -> (
    None
):
    from fdai_document_worker_service.handover import (
        _AGENT_NAMES,
        NullStewardPersonDirectory,
    )

    projection = {
        "map": {
            "version": 1,
            "maintainers": ["maintainer-projected"],
            "hop_timeout_seconds": 900,
            "over_assigned_max": 5,
            "agents": [
                {
                    "name": name,
                    "autonomous": name == "Loki",
                    "accept_autonomous_reason": (
                        "Chaos proposals are always HIL." if name == "Loki" else None
                    ),
                    "stewards": (
                        []
                        if name == "Loki"
                        else [
                            {
                                "kind": "user",
                                "id": "steward-projected",
                                "responsibility": "accountable",
                                "duty": "primary",
                            }
                        ]
                    ),
                }
                for name in _AGENT_NAMES
            ],
        }
    }
    projected = handover_store_module.stewardship_input_from_projection(projection)
    assert projected is not None

    class ProjectedStore(Store):
        async def read_stewardship_input(self) -> StewardshipInput | None:
            return projected

    session, envelope = _session_and_envelope(
        "Agent: Njord; responsibility: accountable; subject: user; identity: steward-projected"
    )
    store = ProjectedStore()
    warnings = await HandoverBootstrapConsumer(
        directory=NullStewardPersonDirectory(),
        store=store,
        stewardship=None,
    ).consume(session=session, envelope=envelope)

    assert warnings == ()
    assert store.artifact is not None
    assert store.artifact.draft.outcome.value == "drafted"
    assert store.artifact.draft.unmapped_agents == ()
    assert store.artifact.draft.unresolved_people == ()
    assert store.artifact.draft.mappings[0].person.oid == "steward-projected"
    assert "accept_autonomous:" in store.artifact.yaml
    assert store.artifact.yaml.count('id: "steward-projected", responsibility: accountable }') == 14


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


def test_worker_and_ingestion_handover_hardening_rounds_h096_to_h103() -> None:
    from fdai_document_worker_service.adapters.handover import PostgresHandoverDraftStore
    from fdai_document_worker_service.handover_interpretation import validate_interpretation
    from fdai_ingestion_api_service.adapters.handover import PostgresHandoverDraftReader
    from fdai_ingestion_api_service.adapters.stewardship import (
        GitHubRepositoryHandoverIntakeConfig,
        GitHubStewardshipWebhookConfig,
        PostgresRepositoryHandoverDraftRecorder,
        PostgresStewardshipMergeRecorder,
    )

    with pytest.raises(ValueError, match="MUST be positive"):
        HandoverGenerationBudget(max_units=True)
    with pytest.raises(ValueError, match="confidence floor"):
        HandoverBootstrapConsumer(
            directory=Directory(),
            store=Store(),
            stewardship=_stewardship_input(),
            confidence_floor=True,
        )
    _, env = _session_and_envelope(
        "Agent: Njord; responsibility: accountable; subject: user; identity: Jane Kim"
    )
    assert (
        validate_interpretation(ReviewedHandoverInterpretation(), env, max_candidates=True) is False
    )
    with pytest.raises(ValueError, match="connect timeout"):
        PostgresHandoverDraftStore(dsn="postgresql://localhost/db", connect_timeout_s=True)
    with pytest.raises(ValueError, match="DSN MUST NOT be empty"):
        PostgresHandoverDraftReader(dsn="   ")
    with pytest.raises(ValueError, match="connect timeout"):
        PostgresHandoverDraftReader(dsn="postgresql://localhost/db", connect_timeout_s=True)
    with pytest.raises(ValueError, match="bounds MUST be positive"):
        GitHubStewardshipWebhookConfig(
            repository="org/repo",
            webhook_secret="x" * 32,
            timeout_seconds=True,
        )
    with pytest.raises(ValueError, match="connect timeout"):
        PostgresStewardshipMergeRecorder(dsn="postgresql://localhost/db", connect_timeout_s=True)
    with pytest.raises(ValueError, match="connect timeout"):
        PostgresRepositoryHandoverDraftRecorder(
            dsn="postgresql://localhost/db", connect_timeout_s=True
        )
    with pytest.raises(ValueError, match="bounds MUST be positive"):
        GitHubRepositoryHandoverIntakeConfig(
            repository="org/repo",
            webhook_secret="x" * 32,
            max_body_bytes=True,
        )
