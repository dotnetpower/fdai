"""Snapshot-bound bulk recorded-state reads; cursors select pages, never authorize them."""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai_operator_service.families.operations.contracts import (
    InventoryImpactContext,
    InventoryInstanceResource,
    ProjectionQuery,
    ProjectionUnavailableError,
)
from fdai_operator_service.families.operations.instance_explorer import (
    _ontology_identity,
    _resource_projection,
    _state_observation,
)
from fdai_service_contracts.ontology_query import content_digest

MAX_STATE_PAGE_SIZE = 500
MAX_STATE_PAGE_OFFSET = 1_000_000_000
STATE_DIRECTORY_EXCLUDED_TYPES = (
    "authorization.role-assignment",
    "resource-group",
    "subscription",
)


class InventoryGenerationChangedError(RuntimeError):
    """The active immutable source changed; clients must discard accumulated pages."""


class OntologyGenerationChangedError(RuntimeError):
    """The active inventory is not the generation currently committed to ontology."""


@dataclass(frozen=True, slots=True)
class InventoryOntologyContext:
    """Committed ontology projection identity for the inventory-owned Resource subgraph."""

    generation: str
    ontology_release_digest: str
    manifest_digest: str


@dataclass(frozen=True, slots=True)
class InventoryStatePage:
    """One id-ordered snapshot page and the count across its complete search result."""

    resources: tuple[InventoryInstanceResource, ...]
    total_count: int


class InventoryStateReader(Protocol):
    """Optional bulk-read port, separate from neighborhood and legacy test readers."""

    async def read_inventory_impact_context(self) -> InventoryImpactContext | None:
        """Return the active immutable generation and cutoff."""
        ...

    async def read_inventory_ontology_context(self) -> InventoryOntologyContext | None:
        """Return the committed inventory-owned ontology generation."""
        ...

    async def read_inventory_state_page(
        self, *, snapshot_id: str, search: str | None, offset: int, limit: int
    ) -> InventoryStatePage:
        """Read one id-ordered page and total in one source statement, excluding containers."""
        ...


async def project_inventory_states(
    *,
    query: ProjectionQuery,
    reader: InventoryStateReader,
    ontology_projection: Mapping[str, object],
    now: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    """Return bounded recorded facts only after active generation and cursor checks.

    Authentication and RBAC are performed afresh by the common route factory.
    The canonical unsigned cursor binds the current source, search, page size,
    release and authenticated context. It cannot supply scope or reader authority.
    """
    search = _search(query)
    release_digest, _ = _ontology_identity(ontology_projection)
    if re.fullmatch(r"sha256:[a-f0-9]{64}", release_digest) is None:
        raise ProjectionUnavailableError("ontology release identity is malformed")
    context = await reader.read_inventory_impact_context()
    if context is None:
        if query.cursor is not None:
            raise InventoryGenerationChangedError
        raise ProjectionUnavailableError("active inventory snapshot is unavailable")
    if (
        not context.snapshot_id
        or len(context.snapshot_id) > 256
        or context.observed_at.tzinfo is None
        or context.observed_at.utcoffset() is None
    ):
        raise ProjectionUnavailableError("active inventory snapshot identity is malformed")
    ontology_context = await reader.read_inventory_ontology_context()
    if (
        ontology_context is not None
        and re.fullmatch(
            r"sha256:[a-f0-9]{64}",
            ontology_context.manifest_digest,
        )
        is None
    ):
        raise ProjectionUnavailableError("inventory ontology manifest identity is malformed")
    if ontology_context is None or (
        ontology_context.generation != context.snapshot_id
        or ontology_context.ontology_release_digest != release_digest
    ):
        raise OntologyGenerationChangedError
    binding = {
        "schema_version": "1.0.0",
        "generation": content_digest({"source_generation": context.snapshot_id}),
        "cutoff": context.observed_at.isoformat(),
        "ontology_manifest_digest": ontology_context.manifest_digest,
        "query_digest": content_digest(
            {
                "operation": query.operation,
                "search": search,
                "limit": query.limit,
                "ontology_release_digest": release_digest,
            }
        ),
        "context_digest": content_digest(
            {
                "principal_id": query.principal_id,
                "roles": sorted(role.value for role in query.roles),
                "purpose": query.purpose,
            }
        ),
    }
    offset = _offset(query.cursor, binding)
    page = await reader.read_inventory_state_page(
        snapshot_id=context.snapshot_id, search=search, offset=offset, limit=query.limit
    )
    active = await reader.read_inventory_impact_context()
    active_ontology = await reader.read_inventory_ontology_context()
    if (
        active is None
        or (active.snapshot_id, active.observed_at)
        != (
            context.snapshot_id,
            context.observed_at,
        )
        or active_ontology != ontology_context
    ):
        raise InventoryGenerationChangedError
    _validate_page(page, offset=offset, limit=query.limit)
    next_offset = offset + len(page.resources)
    complete = next_offset == page.total_count
    evaluated_at = (now or (lambda: datetime.now(UTC)))()
    return {
        "schema_version": "1.0.0",
        "ontology_release_digest": release_digest,
        "ontology_generation": ontology_context.generation,
        "ontology_manifest_digest": ontology_context.manifest_digest,
        "source_kind": "inventory_snapshot_resource",
        "source_generation": context.snapshot_id,
        "source_cutoff": context.observed_at.isoformat(),
        "resources": [
            _resource_projection(
                resource,
                root_id=None,
                now=evaluated_at,
                state_observation=_state_observation(resource, context),
            )
            for resource in page.resources
        ],
        "total_count": page.total_count,
        "next_cursor": None if complete else _encode({**binding, "offset": next_offset}),
        "complete": complete,
        "execution_authority": False,
        "mutation_authority": False,
    }


def _search(query: ProjectionQuery) -> str | None:
    if set(query.params) - {"limit", "cursor", "search"} or any(
        len(values) != 1 for values in query.params.values()
    ):
        raise ValueError("states accepts only one limit, cursor, and search parameter")
    if isinstance(query.limit, bool) or not 1 <= query.limit <= MAX_STATE_PAGE_SIZE:
        raise ValueError("states limit MUST be in [1, 500]")
    raw = query.params.get("search", ("",))[0]
    if len(raw) > 256:
        raise ValueError("states search MUST be at most 256 characters")
    return raw.strip() or None


def _encode(payload: Mapping[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _offset(cursor: str | None, binding: Mapping[str, str]) -> int:
    if cursor is None:
        return 0
    if len(cursor) > 1024 or re.fullmatch(r"[A-Za-z0-9_-]+", cursor) is None:
        raise ValueError("invalid states cursor")
    try:
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        payload = json.loads(raw)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid states cursor") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {*binding, "offset"}
        or any(not isinstance(payload.get(key), str) for key in binding)
        or payload.get("schema_version") != "1.0.0"
        or not isinstance(payload.get("offset"), int)
        or isinstance(payload["offset"], bool)
        or not 1 <= payload["offset"] <= MAX_STATE_PAGE_OFFSET
        or _encode(payload) != cursor
    ):
        raise ValueError("invalid states cursor schema")
    if any(payload[key] != binding[key] for key in ("query_digest", "context_digest")):
        raise ValueError("states cursor does not match the current query or principal context")
    if any(
        payload[key] != binding[key] for key in ("generation", "cutoff", "ontology_manifest_digest")
    ):
        raise InventoryGenerationChangedError
    return int(payload["offset"])


def _validate_page(page: InventoryStatePage, *, offset: int, limit: int) -> None:
    ids = [resource.resource_id for resource in page.resources]
    if (
        isinstance(page.total_count, bool)
        or not isinstance(page.total_count, int)
        or not 0 <= page.total_count <= MAX_STATE_PAGE_OFFSET
        or offset > page.total_count
        or len(ids) != min(limit, page.total_count - offset)
        or ids != sorted(set(ids))
        or any(
            resource.resource_type in STATE_DIRECTORY_EXCLUDED_TYPES for resource in page.resources
        )
    ):
        raise ProjectionUnavailableError("recorded Resource page is malformed")
