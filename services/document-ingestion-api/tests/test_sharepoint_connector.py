"""FDAI-native cross-tenant SharePoint connector tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs
from uuid import UUID

import httpx
import pytest
from azure.core.credentials import AccessToken
from fdai_ingestion_api_service.adapters.sharepoint import (
    MicrosoftGraphSharePointDeltaSource,
    SharePointDeltaConfig,
    SharePointDeltaCursor,
    SharePointDeltaItem,
    SharePointPendingPage,
    SharePointRevisionSupersededError,
)
from fdai_ingestion_api_service.adapters.sharepoint_identity import (
    FederatedManagedIdentityGraphCredential,
    SharePointFederatedCredentialConfig,
)
from fdai_ingestion_api_service.adapters.sharepoint_state import (
    ConnectorBindingConflictError,
    ConnectorDocumentBinding,
    PostgresSharePointDeltaStore,
    _cursor,
    _cursor_json,
    _validate_cancellation_revision,
)
from fdai_ingestion_api_service.sharepoint_connector import (
    NativeSharePointDeltaSink,
    SharePointConnectorConfig,
    SharePointConnectorIntake,
)
from fdai_service_contracts import (
    AccessDescriptor,
    DocumentNotFoundError,
    DocumentPurpose,
    DocumentState,
    IngestionCapabilities,
    ProviderUnavailableError,
    RetentionPolicy,
    SourceStorageMode,
    UploadGrant,
    UploadSession,
)

_TENANT_ID = "00000000-0000-0000-0000-000000000000"
_CLIENT_ID = "00000000-0000-0000-0000-000000000001"


class State:
    def __init__(self) -> None:
        self.binding: ConnectorDocumentBinding | None = None
        self.item: SharePointDeltaItem | None = None
        self.pending: list[str] = []
        self.rejections: list[str] = []

    async def get_binding(self, **_kwargs: object) -> ConnectorDocumentBinding | None:
        return self.binding

    async def apply_batch(self, *, items: Sequence[SharePointDeltaItem], **_kwargs: object) -> None:
        item = items[0]
        if (
            self.item is not None
            and item.source_sequence is not None
            and self.item.source_sequence is not None
            and item.source_sequence < self.item.source_sequence
        ):
            return
        self.item = item

    async def event_matches(self, **values: object) -> bool:
        item = self.item
        return bool(
            item is not None
            and item.source_item_id == values["source_item_id"]
            and item.source_revision == values["source_revision"]
            and item.source_sequence == values["source_sequence"]
            and item.source_name == values["source_name"]
            and item.size_bytes == values["size_bytes"]
            and item.content_sha256 == values["content_sha256"]
            and item.deleted is values["deleted"]
        )

    async def bind_document(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        source_revision: str,
        **_kwargs: object,
    ) -> None:
        prior = self.binding
        if prior is not None and prior.version_id != version_id:
            self.pending.append(prior.source_revision)
        self.binding = ConnectorDocumentBinding(
            document_id=document_id,
            version_id=version_id,
            source_revision=source_revision,
        )

    async def pending_cancellations(self, **_kwargs: object) -> tuple[str, ...]:
        return tuple(self.pending[:64])

    async def pending_cancellation_items(self, **_kwargs: object) -> tuple[str, ...]:
        return ("item-1",) if self.pending else ()

    async def complete_cancellation(self, *, source_revision: str, **_kwargs: object) -> None:
        self.pending = [revision for revision in self.pending if revision != source_revision]

    async def queue_cancellation(self, *, source_revision: str, **_kwargs: object) -> None:
        if source_revision not in self.pending:
            self.pending.append(source_revision)

    async def record_rejection(self, *, failure_code: str, **_kwargs: object) -> None:
        self.rejections.append(failure_code)

    async def finalize_resync(self, **_kwargs: object) -> bool:
        return True

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
        return UploadGrant(upload_id, "memory://upload", session.expires_at)

    async def cancel_upload(self, *, upload_id: UUID, **_kwargs: object) -> UploadSession:
        session = self.uploads[upload_id].model_copy(
            update={"state": DocumentState.DELETING, "revision": 4}
        )
        self.uploads[upload_id] = session
        return session


class Deletion:
    async def delete(self, **_kwargs: object) -> object:
        return object()


class Source:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.downloaded: list[str] = []

    async def download(
        self,
        source_item_id: str,
        *,
        source_revision: str,
        expected_size: int,
        max_size: int,
    ) -> bytes:
        assert source_revision
        assert expected_size == len(self.content)
        assert max_size >= expected_size
        self.downloaded.append(source_item_id)
        return self.content


def _config() -> SharePointConnectorConfig:
    return SharePointConnectorConfig(
        connector_id="sharepoint-operations",
        target_tenant_id=_TENANT_ID,
        collection_id="shared-knowledge",
        access_descriptor_ref="collection:shared-knowledge",
        reader_groups=("knowledge-readers",),
        retention_policy_version="retention-v1",
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
    )


def _intake(service: Service, state: State) -> SharePointConnectorIntake:
    return SharePointConnectorIntake(
        config=_config(),
        service=service,  # type: ignore[arg-type]
        state=state,
        deletion=Deletion(),
    )


async def test_native_sink_downloads_into_governed_lifecycle() -> None:
    service = Service()
    state = State()
    source = Source(b"%PDF-safe")
    sink = NativeSharePointDeltaSink(
        config=_config(),
        source=source,
        intake=_intake(service, state),
        max_file_size=1024,
    )

    await sink.apply_batch(
        connector_id="sharepoint-operations",
        collection_id="shared-knowledge",
        access_descriptor_ref="collection:shared-knowledge",
        idempotency_key="sharepoint-delta:sharepoint-operations:4:" + "a" * 64,
        sync_epoch=0,
        items=(
            SharePointDeltaItem(
                source_item_id="item-1",
                source_revision="etag-1",
                source_name="runbook.pdf",
                size_bytes=9,
                deleted=False,
                media_type="application/pdf",
            ),
        ),
    )

    assert source.downloaded == ["item-1"]
    assert tuple(service.content.values()) == (b"%PDF-safe",)
    assert state.binding is not None
    request = service.requests[0]
    assert request.collection_id == "shared-knowledge"
    assert request.access_descriptor_ref == "collection:shared-knowledge"


async def test_native_sink_propagates_deletion_without_download() -> None:
    service = Service()
    state = State()
    source = Source(b"not-used")
    sink = NativeSharePointDeltaSink(
        config=_config(),
        source=source,
        intake=_intake(service, state),
        max_file_size=1024,
    )

    await sink.apply_batch(
        connector_id="sharepoint-operations",
        collection_id="shared-knowledge",
        access_descriptor_ref="collection:shared-knowledge",
        idempotency_key="sharepoint-delta:sharepoint-operations:6:" + "b" * 64,
        sync_epoch=0,
        items=(
            SharePointDeltaItem(
                source_item_id="item-1",
                source_revision="deleted",
                source_name=None,
                size_bytes=0,
                deleted=True,
            ),
        ),
    )

    assert source.downloaded == []
    assert state.item is not None and state.item.deleted is True


async def test_repeated_deletion_revision_advances_by_sequence() -> None:
    state = State()
    intake = _intake(Service(), state)

    await intake.delete(
        actor_id="sharepoint-connector:reconciler",
        source_item_id="item-1",
        source_revision="deleted",
        source_sequence=4,
    )
    await intake.delete(
        actor_id="sharepoint-connector:reconciler",
        source_item_id="item-1",
        source_revision="deleted",
        source_sequence=6,
    )

    assert state.item is not None
    assert state.item.source_sequence == 6


async def test_native_sink_coalesces_duplicate_delta_items_last_wins() -> None:
    service = Service()
    state = State()
    source = Source(b"%PDF-safe")
    sink = NativeSharePointDeltaSink(
        config=_config(),
        source=source,
        intake=_intake(service, state),
        max_file_size=1024,
    )

    await sink.apply_batch(
        connector_id="sharepoint-operations",
        collection_id="shared-knowledge",
        access_descriptor_ref="collection:shared-knowledge",
        idempotency_key="sharepoint-delta:sharepoint-operations:8:" + "c" * 64,
        sync_epoch=0,
        items=(
            SharePointDeltaItem(
                "item-1", "etag-1", "old.pdf", 9, False, media_type="application/pdf"
            ),
            SharePointDeltaItem(
                "item-1", "etag-2", "runbook.pdf", 9, False, media_type="application/pdf"
            ),
        ),
    )

    assert source.downloaded == ["item-1"]
    assert len(service.requests) == 1
    assert state.item is not None and state.item.source_revision == "etag-2"


async def test_native_sink_records_terminal_policy_rejection() -> None:
    service = Service()
    state = State()
    source = Source(b"not-downloaded")
    sink = NativeSharePointDeltaSink(
        config=_config(),
        source=source,
        intake=_intake(service, state),
        max_file_size=4,
    )

    await sink.apply_batch(
        connector_id="sharepoint-operations",
        collection_id="shared-knowledge",
        access_descriptor_ref="collection:shared-knowledge",
        idempotency_key="sharepoint-delta:sharepoint-operations:10:" + "d" * 64,
        sync_epoch=0,
        items=(
            SharePointDeltaItem(
                "item-1", "etag-1", "large.pdf", 10, False, media_type="application/pdf"
            ),
        ),
    )

    assert source.downloaded == []
    assert state.rejections == ["source_too_large"]


async def test_native_sink_skips_superseded_download_revision() -> None:
    class SupersededSource(Source):
        async def download(self, *_args: object, **_kwargs: object) -> bytes:
            raise SharePointRevisionSupersededError("changed")

    state = State()
    sink = NativeSharePointDeltaSink(
        config=_config(),
        source=SupersededSource(b""),
        intake=_intake(Service(), state),
        max_file_size=1024,
    )

    await sink.apply_batch(
        connector_id="sharepoint-operations",
        collection_id="shared-knowledge",
        access_descriptor_ref="collection:shared-knowledge",
        idempotency_key="sharepoint-delta:sharepoint-operations:12:" + "e" * 64,
        sync_epoch=0,
        items=(
            SharePointDeltaItem(
                "item-1", "etag-1", "runbook.pdf", 9, False, media_type="application/pdf"
            ),
        ),
    )

    assert state.rejections == ["source_revision_superseded"]


async def test_intake_retry_uses_one_deterministic_upload() -> None:
    service = Service()
    state = State()
    intake = _intake(service, state)

    first = await intake.ingest(
        actor_id="sharepoint-connector:reconciler",
        source_item_id="item-1",
        source_revision="etag-1",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-safe",
        source_sequence=2,
    )
    replay = await intake.ingest(
        actor_id="sharepoint-connector:reconciler",
        source_item_id="item-1",
        source_revision="etag-1",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-safe",
        source_sequence=2,
    )

    assert replay.upload_id == first.upload_id
    assert len(service.requests) == 1


async def test_new_revision_cancels_displaced_unprocessed_upload() -> None:
    service = Service()
    state = State()
    intake = _intake(service, state)
    first = await intake.ingest(
        actor_id="sharepoint-connector:reconciler",
        source_item_id="item-1",
        source_revision="etag-1",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-v1",
        source_sequence=2,
    )
    second = await intake.ingest(
        actor_id="sharepoint-connector:reconciler",
        source_item_id="item-1",
        source_revision="etag-2",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-v2",
        source_sequence=4,
    )

    assert first.document_id == second.document_id
    assert first.version_id != second.version_id
    assert service.uploads[first.upload_id].state is DocumentState.DELETING
    assert state.pending == []


async def test_cancellation_failure_remains_retryable() -> None:
    class FlakyService(Service):
        def __init__(self) -> None:
            super().__init__()
            self.fail_once = True

        async def cancel_upload(self, **kwargs: object) -> UploadSession:
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError("transient cancellation failure")
            return await super().cancel_upload(**kwargs)

    service = FlakyService()
    state = State()
    intake = _intake(service, state)
    first = await intake.ingest(
        actor_id="sharepoint-connector:reconciler",
        source_item_id="item-1",
        source_revision="etag-1",
        source_name="runbook.pdf",
        media_type="application/pdf",
        content=b"%PDF-v1",
        source_sequence=2,
    )
    with pytest.raises(RuntimeError, match="transient cancellation"):
        await intake.ingest(
            actor_id="sharepoint-connector:reconciler",
            source_item_id="item-1",
            source_revision="etag-2",
            source_name="runbook.pdf",
            media_type="application/pdf",
            content=b"%PDF-v2",
            source_sequence=4,
        )
    assert state.pending == ["etag-1"]

    await intake.reconcile_cancellations(
        actor_id="sharepoint-connector:reconciler",
        limit=1,
    )

    assert service.uploads[first.upload_id].state is DocumentState.DELETING
    assert state.pending == []


async def test_stale_binding_does_not_queue_winning_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Cursor:
        def __init__(self, row: dict[str, object] | None) -> None:
            self._row = row

        async def fetchone(self) -> dict[str, object] | None:
            return self._row

    class Connection:
        def __init__(self) -> None:
            self.queued = False

        async def __aenter__(self) -> Connection:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def transaction(self) -> Connection:
            return self

        async def execute(self, query: str, _params: object = None) -> Cursor:
            if query.startswith("SELECT set_config"):
                return Cursor(None)
            if query.startswith("SELECT document_id"):
                return Cursor(
                    {
                        "document_id": UUID(int=1),
                        "version_id": UUID(int=2),
                        "bound_source_revision": "winning-revision",
                    }
                )
            if query.startswith("UPDATE document_connector_item"):
                return Cursor(None)
            if query.startswith("INSERT INTO document_connector_cancellation"):
                self.queued = True
                return Cursor(None)
            raise AssertionError(f"unexpected query: {query}")

    connection = Connection()
    store = PostgresSharePointDeltaStore(dsn="postgresql://local")

    async def connect() -> Connection:
        return connection

    monkeypatch.setattr(store, "_connect", connect)

    with pytest.raises(ConnectorBindingConflictError, match="stale document binding"):
        await store.bind_document(
            connector_id="connector",
            source_item_id="item",
            document_id=UUID(int=3),
            version_id=UUID(int=4),
            source_revision="stale-revision",
            source_sequence=1,
        )

    assert connection.queued is False


async def test_background_cancellation_reconciliation_is_page_bounded() -> None:
    state = State()
    state.pending = [f"etag-{index}" for index in range(65)]
    intake = _intake(Service(), state)

    assert (
        await intake.reconcile_cancellations(
            actor_id="sharepoint-connector:reconciler",
            limit=1,
        )
        == 1
    )
    assert state.pending == ["etag-64"]


async def test_federated_credential_exchanges_uami_assertion_for_target_token() -> None:
    class ManagedIdentity:
        async def get_token(self, scope: str) -> AccessToken:
            assert scope == "api://AzureADTokenExchange/.default"
            return AccessToken("managed-identity-assertion", 4_000_000_000)

    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert request.url.host == "login.microsoftonline.com"
        assert request.url.path.endswith(f"/{_TENANT_ID}/oauth2/v2.0/token")
        assert form["client_id"] == [_CLIENT_ID]
        assert form["client_assertion"] == ["managed-identity-assertion"]
        return httpx.Response(
            200,
            json={"access_token": "graph-token", "expires_in": 3600},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        credential = FederatedManagedIdentityGraphCredential(
            config=SharePointFederatedCredentialConfig(
                target_tenant_id=_TENANT_ID,
                client_id=_CLIENT_ID,
            ),
            managed_identity=ManagedIdentity(),  # type: ignore[arg-type]
            client=client,
        )
        first = await credential.get_token("https://graph.microsoft.com/.default")
        second = await credential.get_token("https://graph.microsoft.com/.default")

    assert first.token == "graph-token"
    assert second is first


async def test_graph_download_follows_only_allowlisted_sharepoint_redirect() -> None:
    class Credential:
        async def get_token(self, *_scopes: str) -> AccessToken:
            return AccessToken("graph-token", 4_000_000_000)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "graph.microsoft.com":
            assert request.headers["authorization"] == "Bearer graph-token"
            assert request.headers["if-match"] == "etag-1"
            return httpx.Response(
                302,
                headers={"location": "https://example.sharepoint.com/download?opaque=1"},
            )
        assert request.url.host == "example.sharepoint.com"
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"content")

    config = SharePointDeltaConfig(
        connector_id="sharepoint-operations",
        site_id="site",
        drive_id="drive",
        collection_id="shared-knowledge",
        access_descriptor_ref="collection:shared-knowledge",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = MicrosoftGraphSharePointDeltaSource(
            config=config,
            credential=Credential(),
            client=client,
        )
        content = await source.download(
            "item-1", source_revision="etag-1", expected_size=7, max_size=10
        )

    assert content == b"content"


async def test_graph_download_rejects_untrusted_redirect() -> None:
    class Credential:
        async def get_token(self, *_scopes: str) -> AccessToken:
            return AccessToken("graph-token", 4_000_000_000)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                302, headers={"location": "https://untrusted.example/download"}
            )
        )
    ) as client:
        source = MicrosoftGraphSharePointDeltaSource(
            config=SharePointDeltaConfig(
                connector_id="sharepoint-operations",
                site_id="site",
                drive_id="drive",
                collection_id="shared-knowledge",
                access_descriptor_ref="collection:shared-knowledge",
            ),
            credential=Credential(),
            client=client,
        )
        with pytest.raises(ProviderUnavailableError, match="redirect"):
            await source.download("item-1", source_revision="etag-1", expected_size=1, max_size=10)


async def test_graph_download_rejects_superseded_revision() -> None:
    class Credential:
        async def get_token(self, *_scopes: str) -> AccessToken:
            return AccessToken("graph-token", 4_000_000_000)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(412, content=b"changed"))
    ) as client:
        source = MicrosoftGraphSharePointDeltaSource(
            config=SharePointDeltaConfig(
                connector_id="sharepoint-operations",
                site_id="site",
                drive_id="drive",
                collection_id="shared-knowledge",
                access_descriptor_ref="collection:shared-knowledge",
            ),
            credential=Credential(),
            client=client,
        )
        with pytest.raises(SharePointRevisionSupersededError):
            await source.download("item-1", source_revision="etag-1", expected_size=7, max_size=10)


async def test_graph_download_aborts_when_stream_exceeds_bound() -> None:
    class Credential:
        async def get_token(self, *_scopes: str) -> AccessToken:
            return AccessToken("graph-token", 4_000_000_000)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"too-large"))
    ) as client:
        source = MicrosoftGraphSharePointDeltaSource(
            config=SharePointDeltaConfig(
                connector_id="sharepoint-operations",
                site_id="site",
                drive_id="drive",
                collection_id="shared-knowledge",
                access_descriptor_ref="collection:shared-knowledge",
            ),
            credential=Credential(),
            client=client,
        )
        with pytest.raises(ProviderUnavailableError, match="binding|exceeds"):
            await source.download("item-1", source_revision="etag-1", expected_size=4, max_size=4)


def test_pending_cursor_roundtrip_preserves_media_type() -> None:
    cursor = SharePointDeltaCursor(
        connector_id="sharepoint-operations",
        revision=1,
        delta_url=None,
        binding_digest="a" * 64,
        pending=SharePointPendingPage(
            binding_digest="a" * 64,
            idempotency_key="sharepoint-delta:sharepoint-operations:0:" + "b" * 64,
            items=(
                SharePointDeltaItem(
                    "item-1",
                    "etag-1",
                    "runbook.pdf",
                    9,
                    False,
                    media_type="application/pdf",
                ),
            ),
            continuation_url="https://graph.microsoft.com/v1.0/next",
            has_more=True,
        ),
    )

    restored = _cursor(_cursor_json(cursor))

    assert restored.pending is not None
    assert restored.pending.items[0].media_type == "application/pdf"


@pytest.mark.parametrize("revision", ["", "x" * 513])
def test_cancellation_revision_is_bounded(revision: str) -> None:
    with pytest.raises(ValueError, match=r"\[1, 512\]"):
        _validate_cancellation_revision(revision)


def test_repository_has_no_power_platform_runtime_dependency() -> None:
    root = Path(__file__).resolve().parents[3]
    paths = (
        root / "services" / "document-ingestion-api" / "src",
        root / "infra",
        root / "config",
    )
    offenders = []
    for directory in paths:
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".tf", ".yaml", ".yml"}:
                continue
            text = path.read_text(encoding="utf-8")
            if "power_platform" in text.casefold() or "power platform" in text.casefold():
                offenders.append(path.relative_to(root).as_posix())
    assert offenders == []
