"""Cross-tenant Power Platform connector tests."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai_ingestion_api_service import auth as auth_module
from fdai_ingestion_api_service.adapters.sharepoint import SharePointDeltaItem
from fdai_ingestion_api_service.adapters.sharepoint_state import (
    ConnectorBindingConflictError,
    ConnectorDocumentBinding,
)
from fdai_ingestion_api_service.auth import (
    AuthenticationError,
    Authenticator,
    GroupMapping,
    MultiTenantEntraJwtVerifier,
)
from fdai_ingestion_api_service.http import build_app
from fdai_ingestion_api_service.power_platform import (
    PowerPlatformConnectorAuthenticator,
    PowerPlatformConnectorConfig,
    PowerPlatformSharePointConnector,
)
from fdai_service_contracts import (
    AccessDescriptor,
    DocumentNotFoundError,
    DocumentPurpose,
    DocumentState,
    IngestionCapabilities,
    RetentionPolicy,
    SourceStorageMode,
    UploadGrant,
    UploadSession,
)
from starlette.testclient import TestClient

_M365_TENANT = "00000000-0000-0000-0000-000000000000"


class State:
    def __init__(self) -> None:
        self.binding: ConnectorDocumentBinding | None = None
        self.items: list[SharePointDeltaItem] = []
        self.keys: list[str] = []
        self.sequence: int | None = None
        self.pending: list[str] = []

    async def get_binding(self, **_kwargs: object) -> ConnectorDocumentBinding | None:
        return self.binding

    async def apply_batch(
        self,
        *,
        idempotency_key: str,
        items: tuple[SharePointDeltaItem, ...],
        **_kwargs: object,
    ) -> None:
        self.keys.append(idempotency_key)
        item = items[0]
        if (
            item.source_sequence is not None
            and self.sequence is not None
            and item.source_sequence < self.sequence
        ):
            return
        if (
            item.source_sequence is not None
            and item.source_sequence == self.sequence
            and self.items
            and item != self.items[-1]
        ):
            return
        self.sequence = item.source_sequence
        self.items.extend(items)

    async def event_matches(
        self,
        *,
        source_revision: str,
        source_sequence: int,
        source_name: str | None,
        size_bytes: int,
        content_sha256: str | None,
        deleted: bool,
        **_kwargs: object,
    ) -> bool:
        return bool(
            self.items
            and self.sequence == source_sequence
            and self.items[-1].source_revision == source_revision
            and self.items[-1].source_name == source_name
            and self.items[-1].size_bytes == size_bytes
            and self.items[-1].content_sha256 == content_sha256
            and self.items[-1].deleted is deleted
        )

    async def bind_document(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        source_revision: str,
        source_sequence: int,
        **_kwargs: object,
    ) -> None:
        if self.sequence != source_sequence:
            raise ConnectorBindingConflictError("superseded")
        prior = self.binding
        if prior is not None and prior.version_id != version_id:
            self.pending.append(prior.source_revision)
        self.binding = ConnectorDocumentBinding(
            document_id=document_id,
            version_id=version_id,
            source_revision=source_revision,
        )

    async def pending_cancellations(self, **_kwargs: object) -> tuple[str, ...]:
        return tuple(self.pending)

    async def complete_cancellation(self, *, source_revision: str, **_kwargs: object) -> None:
        self.pending = [revision for revision in self.pending if revision != source_revision]

    async def queue_cancellation(self, *, source_revision: str, **_kwargs: object) -> None:
        if source_revision not in self.pending:
            self.pending.append(source_revision)


class Service:
    def __init__(self) -> None:
        self.uploads: dict[UUID, UploadSession] = {}
        self.requests: list[object] = []
        self.content: dict[UUID, bytes] = {}

    @property
    def capabilities(self) -> IngestionCapabilities:
        return IngestionCapabilities(
            supported_formats=("pdf",),
            storage_modes=(SourceStorageMode.MANAGED_COPY,),
            max_file_size=1024,
            max_batch_count=1,
            archives_enabled=False,
            policy_versions=("retention-v1",),
        )

    async def get_upload(self, *, upload_id: UUID, **_kwargs: object) -> UploadSession:
        try:
            return self.uploads[upload_id]
        except KeyError as exc:
            raise DocumentNotFoundError("missing") from exc

    async def create_upload(self, *, actor_id: str, request: object, **_kwargs: object) -> object:
        self.requests.append(request)
        now = datetime.now(tz=UTC)
        assert request.upload_id is not None
        assert request.document_id is not None
        assert request.version_id is not None
        session = UploadSession(
            upload_id=request.upload_id,
            document_id=request.document_id,
            version_id=request.version_id,
            actor_id=actor_id,
            source_name=request.source_name,
            collection_id=request.collection_id,
            object_key=f"quarantine/{request.upload_id.hex}",
            media_type_hint=request.media_type_hint,
            expected_size=request.expected_size,
            expected_sha256=request.expected_sha256,
            state=DocumentState.UPLOADING,
            storage_mode=SourceStorageMode.MANAGED_COPY,
            purposes=request.purposes,
            access=AccessDescriptor(
                reference=request.access_descriptor_ref,
                collection_id=request.collection_id,
                reader_groups=request.reader_groups,
            ),
            retention=RetentionPolicy(policy_version=request.retention_policy_version),
            created_at=now,
            expires_at=now + timedelta(minutes=15),
            supersedes_version_id=request.supersedes_version_id,
            revision=2,
        )
        self.uploads[session.upload_id] = session
        return session, UploadGrant(
            upload_id=session.upload_id,
            target="memory://upload",
            expires_at=session.expires_at,
        )

    async def put_streaming_content(
        self,
        *,
        upload_id: UUID,
        chunks: AsyncIterator[bytes],
        **_kwargs: object,
    ) -> None:
        self.content[upload_id] = b"".join([chunk async for chunk in chunks])

    async def complete_upload(self, *, upload_id: UUID, **_kwargs: object) -> UploadSession:
        session = self.uploads[upload_id].model_copy(
            update={"state": DocumentState.RECEIVED, "revision": 3}
        )
        self.uploads[upload_id] = session
        return session

    async def resume_upload(self, *, upload_id: UUID, **_kwargs: object) -> UploadGrant:
        session = self.uploads[upload_id].model_copy(
            update={"state": DocumentState.UPLOADING, "revision": 2}
        )
        self.uploads[upload_id] = session
        return UploadGrant(
            upload_id=upload_id,
            target="memory://upload",
            expires_at=session.expires_at,
        )

    async def cancel_upload(self, *, upload_id: UUID, **_kwargs: object) -> UploadSession:
        session = self.uploads[upload_id].model_copy(
            update={"state": DocumentState.DELETING, "revision": 4}
        )
        self.uploads[upload_id] = session
        return session


def _config() -> PowerPlatformConnectorConfig:
    return PowerPlatformConnectorConfig(
        connector_id="sharepoint-operations",
        source_tenant_id=_M365_TENANT,
        collection_id="shared-knowledge",
        access_descriptor_ref="collection:shared-knowledge",
        reader_groups=("knowledge-readers",),
        retention_policy_version="retention-v1",
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
    )


def _connector_client(service: Service, state: State) -> TestClient:
    config = _config()
    connector = PowerPlatformSharePointConnector(
        config=config,
        service=service,  # type: ignore[arg-type]
        state=state,
    )
    connector_authenticator = PowerPlatformConnectorAuthenticator(
        verifier=lambda _token: {
            "tid": _M365_TENANT,
            "oid": "operator",
            "scp": "DocumentConnector.Ingest",
        },
        config=config,
    )
    app = build_app(
        authenticator=Authenticator(
            verifier=lambda _token: {"oid": "operator", "roles": ["Owner"]},
            mapping=GroupMapping("r", "c", "a", "o", "b"),
        ),
        service=service,  # type: ignore[arg-type]
        deletion=object(),  # type: ignore[arg-type]
        power_platform_connector=connector,
        power_platform_authenticator=connector_authenticator,
    )
    return TestClient(app)


def test_http_connector_route_authenticates_and_enters_governed_upload() -> None:
    service = Service()
    state = State()

    with _connector_client(service, state) as client:
        response = client.put(
            "/ingestion/connectors/power-platform/sharepoint-operations/items/item-1/content",
            headers={
                "Authorization": "Bearer connector-token",
                "Content-Type": "application/pdf",
                "x-fdai-source-revision": "etag-1",
                "x-fdai-source-name": "runbook.pdf",
                "x-fdai-event-sequence": "1",
            },
            content=b"%PDF-safe",
        )

    assert response.status_code == 202
    assert response.json()["state"] == DocumentState.RECEIVED.value
    assert tuple(service.content.values()) == (b"%PDF-safe",)
    assert state.binding is not None


def test_http_connector_route_rejects_wrong_policy_binding() -> None:
    with _connector_client(Service(), State()) as client:
        response = client.put(
            "/ingestion/connectors/power-platform/other/items/item-1/content",
            headers={
                "Authorization": "Bearer connector-token",
                "Content-Type": "application/pdf",
                "x-fdai-source-revision": "etag-1",
                "x-fdai-source-name": "runbook.pdf",
                "x-fdai-event-sequence": "1",
            },
            content=b"%PDF-safe",
        )

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


async def test_cross_tenant_connector_uses_fixed_policy_and_retry_ids() -> None:
    service = Service()
    state = State()
    connector = PowerPlatformSharePointConnector(
        config=_config(),
        service=service,  # type: ignore[arg-type]
        state=state,
    )

    first = await connector.ingest(
        actor_id="power-platform:sharepoint-operations:operator",
        source_item_id="item-1",
        source_revision="etag-1",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-safe",
        source_sequence=1,
    )
    replay = await connector.ingest(
        actor_id="power-platform:sharepoint-operations:operator",
        source_item_id="item-1",
        source_revision="etag-1",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-safe",
        source_sequence=1,
    )

    assert first.upload_id == replay.upload_id
    assert len(service.requests) == 1
    request = service.requests[0]
    assert request.collection_id == "shared-knowledge"
    assert request.access_descriptor_ref == "collection:shared-knowledge"
    assert request.reader_groups == ("knowledge-readers",)
    assert state.binding is not None
    assert state.binding.source_revision == "etag-1"


async def test_changed_revision_reuses_document_and_supersedes_version() -> None:
    service = Service()
    state = State()
    connector = PowerPlatformSharePointConnector(
        config=_config(),
        service=service,  # type: ignore[arg-type]
        state=state,
    )
    first = await connector.ingest(
        actor_id="connector",
        source_item_id="item-1",
        source_revision="etag-1",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-v1",
        source_sequence=1,
    )
    second = await connector.ingest(
        actor_id="connector",
        source_item_id="item-1",
        source_revision="etag-2",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-v2",
        source_sequence=2,
    )

    assert first.document_id == second.document_id
    assert first.version_id != second.version_id
    assert service.requests[1].supersedes_version_id == first.version_id
    assert service.uploads[first.upload_id].state is DocumentState.DELETING


async def test_delete_emits_stable_tombstone_without_content() -> None:
    state = State()
    connector = PowerPlatformSharePointConnector(
        config=_config(),
        service=Service(),  # type: ignore[arg-type]
        state=state,
    )

    await connector.delete(
        actor_id="connector",
        source_item_id="item-1",
        source_revision="deleted-2",
        source_sequence=2,
    )
    await connector.delete(
        actor_id="connector",
        source_item_id="item-1",
        source_revision="deleted-2",
        source_sequence=2,
    )

    assert state.items[-1].deleted is True
    assert state.items[-1].source_name is None
    assert state.keys[0] == state.keys[1]


async def test_out_of_order_event_cannot_replace_newer_item() -> None:
    service = Service()
    state = State()
    connector = PowerPlatformSharePointConnector(
        config=_config(),
        service=service,  # type: ignore[arg-type]
        state=state,
    )
    await connector.ingest(
        actor_id="connector",
        source_item_id="item-1",
        source_revision="etag-2",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-v2",
        source_sequence=2,
    )

    with pytest.raises(RuntimeError, match="superseded"):
        await connector.ingest(
            actor_id="connector",
            source_item_id="item-1",
            source_revision="etag-1",
            source_name="runbook.pdf",
            media_type="application/pdf",
            content=b"%PDF-v1",
            source_sequence=1,
        )

    assert len(service.requests) == 1
    assert state.binding is not None
    assert state.binding.source_revision == "etag-2"


async def test_same_revision_cannot_change_content_after_state_was_persisted() -> None:
    service = Service()
    state = State()
    config = _config()
    connector = PowerPlatformSharePointConnector(
        config=config,
        service=service,  # type: ignore[arg-type]
        state=state,
    )
    await state.apply_batch(
        connector_id=config.binding_id,
        collection_id=config.collection_id,
        access_descriptor_ref=config.access_descriptor_ref,
        idempotency_key=f"power-platform:{config.binding_id}:item-1:etag-1",
        items=(
            SharePointDeltaItem(
                source_item_id="item-1",
                source_revision="etag-1",
                source_name="runbook.pdf",
                size_bytes=len(b"%PDF-original"),
                content_sha256=hashlib.sha256(b"%PDF-original").hexdigest(),
                deleted=False,
                source_sequence=1,
            ),
        ),
    )

    with pytest.raises(RuntimeError, match="superseded"):
        await connector.ingest(
            actor_id="connector",
            source_item_id="item-1",
            source_revision="etag-1",
            source_name="runbook.pdf",
            media_type="application/pdf",
            content=b"%PDF-substituted",
            source_sequence=1,
        )

    assert service.requests == []


async def test_event_sequence_must_fit_postgres_bigint() -> None:
    connector = PowerPlatformSharePointConnector(
        config=_config(),
        service=Service(),  # type: ignore[arg-type]
        state=State(),
    )

    with pytest.raises(ValueError, match="signed 64-bit"):
        await connector.ingest(
            actor_id="connector",
            source_item_id="item-1",
            source_revision="etag-1",
            source_name="runbook.pdf",
            media_type="application/pdf",
            content=b"%PDF-safe",
            source_sequence=2**63,
        )


async def test_duplicate_create_race_reloads_deterministic_upload() -> None:
    class RacingService(Service):
        async def create_upload(self, **kwargs: object) -> object:
            await super().create_upload(**kwargs)
            raise ValueError("document upload or version already exists")

    service = RacingService()
    state = State()
    connector = PowerPlatformSharePointConnector(
        config=_config(),
        service=service,  # type: ignore[arg-type]
        state=state,
    )

    session = await connector.ingest(
        actor_id="connector",
        source_item_id="item-1",
        source_revision="etag-1",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-v1",
        source_sequence=1,
    )

    assert session.state is DocumentState.RECEIVED
    assert state.binding is not None


async def test_created_session_is_rolled_forward_before_binding() -> None:
    service = Service()
    state = State()
    connector = PowerPlatformSharePointConnector(
        config=_config(),
        service=service,  # type: ignore[arg-type]
        state=state,
    )
    completed = await connector.ingest(
        actor_id="connector",
        source_item_id="item-1",
        source_revision="etag-1",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-v1",
        source_sequence=1,
    )
    state.binding = None
    service.uploads[completed.upload_id] = completed.model_copy(
        update={"state": DocumentState.CREATED, "revision": 1}
    )

    recovered = await connector.ingest(
        actor_id="connector",
        source_item_id="item-1",
        source_revision="etag-1",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-v1",
        source_sequence=1,
    )

    assert recovered.state is DocumentState.RECEIVED
    assert state.binding is not None


async def test_newer_delete_winning_before_bind_compensates_upload() -> None:
    class DeleteWinsState(State):
        async def bind_document(self, **_kwargs: object) -> None:
            raise ConnectorBindingConflictError("newer deletion won")

    service = Service()
    state = DeleteWinsState()
    connector = PowerPlatformSharePointConnector(
        config=_config(),
        service=service,  # type: ignore[arg-type]
        state=state,
    )

    with pytest.raises(ConnectorBindingConflictError, match="deletion won"):
        await connector.ingest(
            actor_id="connector",
            source_item_id="item-1",
            source_revision="etag-1",
            source_name="runbook.pdf",
            media_type="application/pdf",
            content=b"%PDF-v1",
            source_sequence=1,
        )

    assert next(iter(service.uploads.values())).state is DocumentState.DELETING
    assert service.content == {}


async def test_bind_conflict_failed_cancel_remains_durable() -> None:
    class DeleteWinsState(State):
        async def bind_document(self, **_kwargs: object) -> None:
            raise ConnectorBindingConflictError("newer deletion won")

    class FailedCancellationService(Service):
        async def cancel_upload(self, **_kwargs: object) -> UploadSession:
            raise RuntimeError("cancellation unavailable")

    service = FailedCancellationService()
    state = DeleteWinsState()
    connector = PowerPlatformSharePointConnector(
        config=_config(),
        service=service,  # type: ignore[arg-type]
        state=state,
    )

    with pytest.raises(RuntimeError, match="cancellation unavailable"):
        await connector.ingest(
            actor_id="connector",
            source_item_id="item-1",
            source_revision="etag-1",
            source_name="runbook.pdf",
            media_type="application/pdf",
            content=b"%PDF-v1",
            source_sequence=1,
        )

    assert state.pending == ["etag-1"]


async def test_failed_displaced_cancellation_is_retried_from_durable_state() -> None:
    class FlakyCancellationService(Service):
        def __init__(self) -> None:
            super().__init__()
            self.fail_cancellation = True

        async def cancel_upload(self, **kwargs: object) -> UploadSession:
            if self.fail_cancellation:
                self.fail_cancellation = False
                raise RuntimeError("transient cancellation failure")
            return await super().cancel_upload(**kwargs)

    service = FlakyCancellationService()
    state = State()
    connector = PowerPlatformSharePointConnector(
        config=_config(),
        service=service,  # type: ignore[arg-type]
        state=state,
    )
    first = await connector.ingest(
        actor_id="connector",
        source_item_id="item-1",
        source_revision="etag-1",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-v1",
        source_sequence=1,
    )

    with pytest.raises(RuntimeError, match="transient cancellation"):
        await connector.ingest(
            actor_id="connector",
            source_item_id="item-1",
            source_revision="etag-2",
            source_name="runbook.pdf",
            media_type="application/pdf",
            content=b"%PDF-v2",
            source_sequence=2,
        )
    assert state.pending == ["etag-1"]

    second = await connector.ingest(
        actor_id="connector",
        source_item_id="item-1",
        source_revision="etag-2",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-v2",
        source_sequence=2,
    )

    assert service.uploads[first.upload_id].state is DocumentState.DELETING
    assert second.state is DocumentState.RECEIVED
    assert state.pending == []


async def test_deletion_drains_pending_displaced_cancellations() -> None:
    class FlakyCancellationService(Service):
        def __init__(self) -> None:
            super().__init__()
            self.fail_cancellation = True

        async def cancel_upload(self, **kwargs: object) -> UploadSession:
            if self.fail_cancellation:
                self.fail_cancellation = False
                raise RuntimeError("transient cancellation failure")
            return await super().cancel_upload(**kwargs)

    service = FlakyCancellationService()
    state = State()
    connector = PowerPlatformSharePointConnector(
        config=_config(),
        service=service,  # type: ignore[arg-type]
        state=state,
    )
    first = await connector.ingest(
        actor_id="connector",
        source_item_id="item-1",
        source_revision="etag-1",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-v1",
        source_sequence=1,
    )
    with pytest.raises(RuntimeError, match="transient cancellation"):
        await connector.ingest(
            actor_id="connector",
            source_item_id="item-1",
            source_revision="etag-2",
            source_name="runbook.pdf",
            media_type="application/pdf",
            content=b"%PDF-v2",
            source_sequence=2,
        )

    await connector.delete(
        actor_id="connector",
        source_item_id="item-1",
        source_revision="deleted-3",
        source_sequence=3,
    )

    assert service.uploads[first.upload_id].state is DocumentState.DELETING
    assert state.pending == []


def test_connector_authentication_separates_source_and_api_tenants() -> None:
    authenticator = PowerPlatformConnectorAuthenticator(
        verifier=lambda _token: {
            "tid": _M365_TENANT,
            "oid": "operator",
            "scp": "DocumentConnector.Ingest",
        },
        config=_config(),
    )
    actor = authenticator.authenticate("Bearer signed-token")

    assert actor == "power-platform:sharepoint-operations:operator"


@pytest.mark.parametrize(
    "claims",
    [
        {
            "tid": str(UUID(int=2)),
            "oid": "operator",
            "scp": "DocumentConnector.Ingest",
        },
        {"tid": _M365_TENANT, "oid": "operator", "scp": "User.Read"},
    ],
)
def test_connector_authentication_rejects_wrong_tenant_or_scope(
    claims: dict[str, object],
) -> None:
    authenticator = PowerPlatformConnectorAuthenticator(
        verifier=lambda _token: claims,
        config=_config(),
    )
    with pytest.raises(AuthenticationError):
        authenticator.authenticate("Bearer signed-token")


def test_multi_tenant_verifier_pins_tenant_audience_and_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Jwks:
        def get_signing_key_from_jwt(self, _token: str) -> object:
            return type("Key", (), {"key": "public-key"})()

    calls = 0

    def decode(_token: str, *args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if not args:
            return {"tid": _M365_TENANT}
        return {
            "tid": _M365_TENANT,
            "azp": "power-platform-client",
            "aud": "api://fdai",
            "iss": f"https://login.microsoftonline.com/{_M365_TENANT}/v2.0",
            "exp": 4_000_000_000,
        }

    monkeypatch.setattr(auth_module.jwt, "decode", decode)
    verifier = MultiTenantEntraJwtVerifier(
        jwks_client=Jwks(),  # type: ignore[arg-type]
        audience="api://fdai",
        allowed_tenant_ids=frozenset({_M365_TENANT}),
        allowed_client_ids=frozenset({"power-platform-client"}),
    )

    assert verifier("signed-token")["tid"] == _M365_TENANT
    assert calls == 2


def test_multi_tenant_verifier_rejects_tenant_before_key_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Jwks:
        def get_signing_key_from_jwt(self, _token: str) -> object:
            raise AssertionError("disallowed tenant MUST NOT trigger key lookup")

    monkeypatch.setattr(
        auth_module.jwt,
        "decode",
        lambda *_args, **_kwargs: {"tid": "unexpected-tenant"},
    )
    verifier = MultiTenantEntraJwtVerifier(
        jwks_client=Jwks(),  # type: ignore[arg-type]
        audience="api://fdai",
        allowed_tenant_ids=frozenset({_M365_TENANT}),
        allowed_client_ids=frozenset({"power-platform-client"}),
    )

    with pytest.raises(AuthenticationError, match="tenant is not allowed"):
        verifier("signed-token")


def test_power_platform_routes_are_bound_explicitly() -> None:
    connector = PowerPlatformSharePointConnector(
        config=_config(),
        service=Service(),  # type: ignore[arg-type]
        state=State(),
    )
    connector_auth = PowerPlatformConnectorAuthenticator(
        verifier=lambda _token: {
            "tid": _M365_TENANT,
            "oid": "operator",
            "scp": "DocumentConnector.Ingest",
        },
        config=_config(),
    )
    service = type(
        "HttpService",
        (),
        {
            "capabilities": IngestionCapabilities(
                supported_formats=("pdf",),
                storage_modes=(SourceStorageMode.MANAGED_COPY,),
                max_file_size=1024,
                max_batch_count=1,
                archives_enabled=False,
                policy_versions=("v1",),
            )
        },
    )()
    app = build_app(
        authenticator=Authenticator(
            verifier=lambda _token: {"oid": "operator", "roles": ["Owner"]},
            mapping=GroupMapping("r", "c", "a", "o", "b"),
        ),
        service=service,  # type: ignore[arg-type]
        deletion=object(),  # type: ignore[arg-type]
        power_platform_connector=connector,
        power_platform_authenticator=connector_auth,
    )

    paths = {route.path for route in app.routes}
    assert any(path.endswith("/{source_item_id}/content") for path in paths)
    assert any(path.endswith("/{source_item_id}/deleted") for path in paths)
