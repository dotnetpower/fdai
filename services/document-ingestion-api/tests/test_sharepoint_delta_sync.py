"""Focused SharePoint delta fencing, deletion, and restart tests."""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace

import httpx
import pytest
from fdai_ingestion_api_service.adapters.sharepoint import (
    ConnectorCursorConflictError,
    MicrosoftGraphSharePointDeltaSource,
    SharePointDeltaConfig,
    SharePointDeltaCursor,
    SharePointDeltaItem,
    SharePointDeltaSynchronizer,
    SharePointPendingPage,
)
from fdai_service_contracts import ProviderUnavailableError


class Credential:
    async def get_token(self, *_scopes: str) -> object:
        return SimpleNamespace(token="graph-token")


class CursorStore:
    def __init__(self, *, conflict: bool = False) -> None:
        self.cursor: SharePointDeltaCursor | None = None
        self.conflict = conflict

    async def load(self, _connector_id: str) -> SharePointDeltaCursor | None:
        return self.cursor

    async def compare_and_swap(
        self, *, expected_revision: int, cursor: SharePointDeltaCursor
    ) -> bool:
        if self.conflict:
            return False
        current = 0 if self.cursor is None else self.cursor.revision
        if current != expected_revision:
            return False
        self.cursor = cursor
        return True


class Sink:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.calls: list[tuple[str, str, str, tuple[SharePointDeltaItem, ...]]] = []

    async def apply_batch(
        self,
        *,
        connector_id: str,
        collection_id: str,
        access_descriptor_ref: str,
        idempotency_key: str,
        items: Sequence[SharePointDeltaItem],
    ) -> None:
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("backpressure")
        self.calls.append((collection_id, access_descriptor_ref, idempotency_key, tuple(items)))
        assert connector_id == "sharepoint-primary"


def _config() -> SharePointDeltaConfig:
    return SharePointDeltaConfig(
        connector_id="sharepoint-primary",
        site_id="site-id",
        drive_id="drive-id",
        collection_id="shared-knowledge",
        access_descriptor_ref="acl:sharepoint:operations",
        page_size=3,
        graph_base_url="https://graph.example/v1.0",
        graph_scope="https://graph.example/.default",
    )


async def test_delta_sync_propagates_deletion_and_fences_each_cursor_page() -> None:
    pages = [
        {
            "value": [
                {"id": "1", "eTag": "v1", "name": "guide.pdf", "size": 12, "file": {}},
                {"id": "2", "eTag": "v2", "name": "old.docx", "deleted": {}},
                {"id": "3", "eTag": "v3", "name": "folder", "folder": {}},
            ],
            "@odata.nextLink": "https://graph.example/v1.0/next?page=2",
        },
        {
            "value": [],
            "@odata.deltaLink": "https://graph.example/v1.0/delta?token=stable",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer graph-token"
        return httpx.Response(200, json=pages.pop(0))

    cursors = CursorStore()
    sink = Sink()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = MicrosoftGraphSharePointDeltaSource(
            config=_config(),
            credential=Credential(),  # type: ignore[arg-type]
            client=client,
        )
        applied = await SharePointDeltaSynchronizer(
            config=_config(), source=source, cursors=cursors, sink=sink
        ).synchronize()

    assert applied == 2
    assert sink.calls[0][0:2] == ("shared-knowledge", "acl:sharepoint:operations")
    assert sink.calls[0][3][1].deleted is True
    assert cursors.cursor == SharePointDeltaCursor(
        "sharepoint-primary", 4, "https://graph.example/v1.0/delta?token=stable"
    )


async def test_sink_failure_leaves_cursor_for_idempotent_restart() -> None:
    response = {
        "value": [{"id": "1", "eTag": "v1", "name": "guide.pdf", "size": 12, "file": {}}],
        "@odata.deltaLink": "https://graph.example/v1.0/delta?token=stable",
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    cursors = CursorStore()
    sink = Sink(fail_once=True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = MicrosoftGraphSharePointDeltaSource(
            config=_config(),
            credential=Credential(),  # type: ignore[arg-type]
            client=client,
        )
        synchronizer = SharePointDeltaSynchronizer(
            config=_config(), source=source, cursors=cursors, sink=sink
        )
        with pytest.raises(RuntimeError, match="backpressure"):
            await synchronizer.synchronize()
        assert cursors.cursor is not None
        assert cursors.cursor.pending is not None
        assert await synchronizer.synchronize() == 1

    assert cursors.cursor is not None
    assert cursors.cursor.revision == 2


async def test_ambiguous_sink_success_replays_exact_persisted_page() -> None:
    responses = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal responses
        responses += 1
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "1",
                        "eTag": f"v{responses}",
                        "name": "guide.pdf",
                        "size": 12,
                        "file": {},
                    }
                ],
                "@odata.deltaLink": "https://graph.example/v1.0/delta?token=stable",
            },
        )

    class AmbiguousSink(Sink):
        async def apply_batch(
            self,
            *,
            connector_id: str,
            collection_id: str,
            access_descriptor_ref: str,
            idempotency_key: str,
            items: Sequence[SharePointDeltaItem],
        ) -> None:
            await super().apply_batch(
                connector_id=connector_id,
                collection_id=collection_id,
                access_descriptor_ref=access_descriptor_ref,
                idempotency_key=idempotency_key,
                items=items,
            )
            if len(self.calls) == 1:
                raise TimeoutError("ambiguous success")

    cursors = CursorStore()
    sink = AmbiguousSink()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = MicrosoftGraphSharePointDeltaSource(
            config=_config(),
            credential=Credential(),  # type: ignore[arg-type]
            client=client,
        )
        synchronizer = SharePointDeltaSynchronizer(
            config=_config(), source=source, cursors=cursors, sink=sink
        )
        with pytest.raises(TimeoutError, match="ambiguous"):
            await synchronizer.synchronize()
        assert cursors.cursor is not None
        assert isinstance(cursors.cursor.pending, SharePointPendingPage)
        assert await synchronizer.synchronize() == 1

    assert responses == 1
    assert sink.calls[0][2] == sink.calls[1][2]
    assert sink.calls[0][3] == sink.calls[1][3]


async def test_pending_page_rejects_changed_collection_binding() -> None:
    pending = SharePointPendingPage(
        binding_digest=_config().binding_digest,
        idempotency_key="sharepoint-delta:pending",
        items=(),
        continuation_url="https://graph.example/v1.0/delta?token=stable",
        has_more=False,
    )
    cursors = CursorStore()
    cursors.cursor = SharePointDeltaCursor(
        connector_id="sharepoint-primary",
        revision=1,
        delta_url=None,
        pending=pending,
    )
    changed = SharePointDeltaConfig(
        connector_id="sharepoint-primary",
        site_id="site-id",
        drive_id="drive-id",
        collection_id="other-collection",
        access_descriptor_ref="acl:sharepoint:operations",
        graph_base_url="https://graph.example/v1.0",
        graph_scope="https://graph.example/.default",
    )
    async with httpx.AsyncClient() as client:
        source = MicrosoftGraphSharePointDeltaSource(
            config=changed,
            credential=Credential(),  # type: ignore[arg-type]
            client=client,
        )
        with pytest.raises(ConnectorCursorConflictError, match="binding changed"):
            await SharePointDeltaSynchronizer(
                config=changed, source=source, cursors=cursors, sink=Sink()
            ).synchronize()


async def test_delta_sync_rejects_cursor_race_and_foreign_continuation() -> None:
    def conflicting_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [],
                "@odata.deltaLink": "https://graph.example/v1.0/delta?token=stable",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(conflicting_handler)) as client:
        source = MicrosoftGraphSharePointDeltaSource(
            config=_config(),
            credential=Credential(),  # type: ignore[arg-type]
            client=client,
        )
        with pytest.raises(ConnectorCursorConflictError, match="lost its fence"):
            await SharePointDeltaSynchronizer(
                config=_config(),
                source=source,
                cursors=CursorStore(conflict=True),
                sink=Sink(),
            ).synchronize()

    def foreign_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [],
                "@odata.deltaLink": "https://attacker.example/delta?token=stolen",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(foreign_handler)) as client:
        source = MicrosoftGraphSharePointDeltaSource(
            config=_config(),
            credential=Credential(),  # type: ignore[arg-type]
            client=client,
        )
        with pytest.raises(ProviderUnavailableError, match="origin changed"):
            await source.fetch(None)
