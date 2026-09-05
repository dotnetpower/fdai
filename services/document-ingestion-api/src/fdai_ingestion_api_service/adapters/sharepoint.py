"""Bounded Microsoft Graph/SharePoint delta synchronization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote, urlparse

import httpx
from fdai_service_contracts import ProviderUnavailableError


class _AccessToken(Protocol):
    token: str


class GraphTokenCredential(Protocol):
    async def get_token(self, *scopes: str) -> _AccessToken: ...


@dataclass(frozen=True, slots=True)
class SharePointDeltaConfig:
    connector_id: str
    site_id: str
    drive_id: str
    collection_id: str
    access_descriptor_ref: str
    page_size: int = 100
    max_pages_per_run: int = 20
    graph_base_url: str = "https://graph.microsoft.com/v1.0"
    graph_scope: str = "https://graph.microsoft.com/.default"

    def __post_init__(self) -> None:
        parsed = urlparse(self.graph_base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise ValueError("Graph base URL MUST be an HTTPS URL without query or fragment")
        scope = urlparse(self.graph_scope)
        if (
            scope.scheme != "https"
            or scope.hostname != parsed.hostname
            or scope.port != parsed.port
            or scope.path != "/.default"
            or scope.query
            or scope.fragment
        ):
            raise ValueError("Graph scope MUST match the configured Graph HTTPS origin")
        for name, value in (
            ("connector_id", self.connector_id),
            ("site_id", self.site_id),
            ("drive_id", self.drive_id),
            ("collection_id", self.collection_id),
            ("access_descriptor_ref", self.access_descriptor_ref),
        ):
            if not value or len(value) > 512:
                raise ValueError(f"{name} MUST be non-empty and bounded")
        if not 1 <= self.page_size <= 1000:
            raise ValueError("SharePoint delta page size MUST be in [1, 1000]")
        if not 1 <= self.max_pages_per_run <= 1000:
            raise ValueError("SharePoint delta page count MUST be in [1, 1000]")

    @property
    def binding_digest(self) -> str:
        values = (
            self.connector_id,
            self.site_id,
            self.drive_id,
            self.collection_id,
            self.access_descriptor_ref,
            self.graph_base_url.rstrip("/"),
            self.graph_scope,
        )
        return hashlib.sha256("\0".join(values).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SharePointDeltaCursor:
    connector_id: str
    revision: int
    delta_url: str | None
    binding_digest: str | None = None
    pending: SharePointPendingPage | None = None


@dataclass(frozen=True, slots=True)
class SharePointDeltaItem:
    source_item_id: str
    source_revision: str
    source_name: str | None
    size_bytes: int
    deleted: bool
    source_sequence: int | None = None
    content_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class SharePointDeltaPage:
    items: tuple[SharePointDeltaItem, ...]
    next_url: str | None
    delta_url: str | None


@dataclass(frozen=True, slots=True)
class SharePointPendingPage:
    binding_digest: str
    idempotency_key: str
    items: tuple[SharePointDeltaItem, ...]
    continuation_url: str
    has_more: bool


class SharePointDeltaCursorStore(Protocol):
    async def load(self, connector_id: str) -> SharePointDeltaCursor | None: ...

    async def compare_and_swap(
        self, *, expected_revision: int, cursor: SharePointDeltaCursor
    ) -> bool: ...


class SharePointDeltaSink(Protocol):
    async def apply_batch(
        self,
        *,
        connector_id: str,
        collection_id: str,
        access_descriptor_ref: str,
        idempotency_key: str,
        items: Sequence[SharePointDeltaItem],
    ) -> None: ...


class ConnectorCursorConflictError(RuntimeError):
    """The durable connector cursor changed before this page committed."""


class MicrosoftGraphSharePointDeltaSource:
    """Read one Graph delta page and reject untrusted continuation origins."""

    def __init__(
        self,
        *,
        config: SharePointDeltaConfig,
        credential: GraphTokenCredential,
        client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._credential = credential
        self._client = client
        parsed = urlparse(config.graph_base_url)
        self._origin = (parsed.scheme, parsed.hostname, parsed.port)

    async def fetch(self, delta_url: str | None) -> SharePointDeltaPage:
        url = self._validated_continuation(delta_url) if delta_url else self._initial_url()
        token = await self._credential.get_token(self._config.graph_scope)
        try:
            response = await self._client.get(
                url,
                params=(
                    None
                    if delta_url
                    else {
                        "$select": "id,eTag,name,size,file,deleted",
                        "$top": str(self._config.page_size),
                    }
                ),
                headers={"Authorization": f"Bearer {token.token}"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("SharePoint delta request failed") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderUnavailableError("SharePoint delta response is not JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
            raise ProviderUnavailableError("SharePoint delta response has no value array")
        raw_items = payload["value"]
        if len(raw_items) > self._config.page_size:
            raise ProviderUnavailableError("SharePoint delta page exceeds the configured bound")
        parsed_items = (_delta_item(raw) for raw in raw_items)
        items = tuple(item for item in parsed_items if item is not None)
        next_url = self._optional_continuation(payload.get("@odata.nextLink"))
        delta_result = self._optional_continuation(payload.get("@odata.deltaLink"))
        if next_url is None and delta_result is None:
            raise ProviderUnavailableError("SharePoint delta response has no continuation fence")
        if next_url is not None and delta_result is not None:
            raise ProviderUnavailableError(
                "SharePoint delta response has conflicting continuations"
            )
        return SharePointDeltaPage(items=items, next_url=next_url, delta_url=delta_result)

    def _initial_url(self) -> str:
        site = quote(self._config.site_id, safe="")
        drive = quote(self._config.drive_id, safe="")
        return f"{self._config.graph_base_url.rstrip('/')}/sites/{site}/drives/{drive}/root/delta"

    def _optional_continuation(self, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise ProviderUnavailableError("SharePoint continuation URL is invalid")
        return self._validated_continuation(value)

    def _validated_continuation(self, value: str) -> str:
        parsed = urlparse(value)
        if (parsed.scheme, parsed.hostname, parsed.port) != self._origin:
            raise ProviderUnavailableError("SharePoint continuation origin changed")
        if parsed.fragment or parsed.username or parsed.password:
            raise ProviderUnavailableError("SharePoint continuation URL is unsafe")
        return value


class SharePointDeltaSynchronizer:
    """Apply bounded pages sequentially and fence each durable cursor advance."""

    def __init__(
        self,
        *,
        config: SharePointDeltaConfig,
        source: MicrosoftGraphSharePointDeltaSource,
        cursors: SharePointDeltaCursorStore,
        sink: SharePointDeltaSink,
    ) -> None:
        self._config = config
        self._source = source
        self._cursors = cursors
        self._sink = sink

    async def synchronize(self) -> int:
        cursor = await self._cursors.load(self._config.connector_id)
        if cursor is None:
            cursor = SharePointDeltaCursor(
                self._config.connector_id,
                0,
                None,
                binding_digest=self._config.binding_digest,
            )
        elif cursor.connector_id != self._config.connector_id or cursor.revision < 0:
            raise ConnectorCursorConflictError("SharePoint cursor binding is invalid")
        elif cursor.binding_digest != self._config.binding_digest:
            raise ConnectorCursorConflictError(
                "SharePoint stable cursor configuration binding changed"
            )
        applied = 0
        for _ in range(self._config.max_pages_per_run):
            if cursor.pending is None:
                page = await self._source.fetch(cursor.delta_url)
                continuation_url = page.next_url or page.delta_url
                if continuation_url is None:
                    raise ProviderUnavailableError(
                        "SharePoint delta page has no committed continuation"
                    )
                pending = SharePointPendingPage(
                    binding_digest=self._config.binding_digest,
                    idempotency_key=_batch_key(self._config, cursor, page.items),
                    items=page.items,
                    continuation_url=continuation_url,
                    has_more=page.next_url is not None,
                )
                staged = SharePointDeltaCursor(
                    connector_id=self._config.connector_id,
                    revision=cursor.revision + 1,
                    delta_url=cursor.delta_url,
                    binding_digest=self._config.binding_digest,
                    pending=pending,
                )
                if not await self._cursors.compare_and_swap(
                    expected_revision=cursor.revision, cursor=staged
                ):
                    raise ConnectorCursorConflictError("SharePoint page staging lost its fence")
                cursor = staged
            active_pending = cursor.pending
            if active_pending is None:
                raise ConnectorCursorConflictError("SharePoint pending page was not persisted")
            if active_pending.binding_digest != self._config.binding_digest:
                raise ConnectorCursorConflictError(
                    "SharePoint pending page configuration binding changed"
                )
            await self._sink.apply_batch(
                connector_id=self._config.connector_id,
                collection_id=self._config.collection_id,
                access_descriptor_ref=self._config.access_descriptor_ref,
                idempotency_key=active_pending.idempotency_key,
                items=active_pending.items,
            )
            next_cursor = SharePointDeltaCursor(
                connector_id=self._config.connector_id,
                revision=cursor.revision + 1,
                delta_url=active_pending.continuation_url,
                binding_digest=self._config.binding_digest,
            )
            if not await self._cursors.compare_and_swap(
                expected_revision=cursor.revision, cursor=next_cursor
            ):
                raise ConnectorCursorConflictError("SharePoint cursor advance lost its fence")
            applied += len(active_pending.items)
            cursor = next_cursor
            if not active_pending.has_more:
                return applied
        return applied


def _delta_item(raw: object) -> SharePointDeltaItem | None:
    if not isinstance(raw, dict):
        raise ProviderUnavailableError("SharePoint delta item is invalid")
    item_id = raw.get("id")
    deleted = isinstance(raw.get("deleted"), dict)
    revision = raw.get("eTag")
    if not isinstance(item_id, str) or not item_id:
        raise ProviderUnavailableError("SharePoint delta item id is missing")
    if not isinstance(revision, str) or not revision:
        if deleted:
            revision = "deleted"
        else:
            raise ProviderUnavailableError("SharePoint delta item revision is missing")
    name = raw.get("name")
    if name is not None and (not isinstance(name, str) or not name):
        raise ProviderUnavailableError("SharePoint delta item name is invalid")
    size = raw.get("size", 0)
    if not isinstance(size, int) or size < 0:
        raise ProviderUnavailableError("SharePoint delta item size is invalid")
    if not deleted and isinstance(raw.get("folder"), dict):
        return None
    if not deleted and not isinstance(raw.get("file"), dict):
        raise ProviderUnavailableError("SharePoint delta item is not a file")
    return SharePointDeltaItem(
        source_item_id=item_id,
        source_revision=revision,
        source_name=name,
        size_bytes=size,
        deleted=deleted,
    )


def _batch_key(
    config: SharePointDeltaConfig,
    cursor: SharePointDeltaCursor,
    items: Sequence[SharePointDeltaItem],
) -> str:
    payload = {
        "binding_digest": config.binding_digest,
        "connector_id": config.connector_id,
        "cursor_revision": cursor.revision,
        "items": [[item.source_item_id, item.source_revision, item.deleted] for item in items],
    }
    digest = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return f"sharepoint-delta:{config.connector_id}:{cursor.revision}:{digest}"
