"""Azure Resource Graph query factory — turns a
:class:`~aiopspilot.shared.providers.inventory.Inventory` shard call into a
real Kusto-over-ARG REST request.

Design boundaries
-----------------

- ``core/`` never imports this module. It sits under ``delivery/azure/`` and
  is bound at the composition root through the existing
  :type:`~aiopspilot.delivery.azure.inventory.ResourceQueryFn` seam
  (a plain async callable). The
  :class:`~aiopspilot.delivery.azure.inventory.AzureResourceGraphInventory`
  keeps its bounded-concurrency + atomic-promote fence guarantees; this
  file adds only the "how do I fetch one shard from ARG" concern.
- Identity flows through the injected
  :class:`~aiopspilot.shared.providers.workload_identity.WorkloadIdentity`
  Protocol — no ``DefaultAzureCredential``, no ``azure-identity`` import.
  A fork MAY plug in IRSA / SPIFFE / GCP-WIF under the same seam.
- HTTP transport is an injected :class:`httpx.AsyncClient`. Tests pass a
  client backed by :class:`httpx.MockTransport`; production wires a
  long-lived shared client at the composition root.
- Kusto query and CSP-neutral → ARM-type mapping come from
  :class:`~aiopspilot.rule_catalog.schema.resource_type.ResourceTypeRegistry`
  (the ``azure_arm_type`` field). Resource types with ``azure_arm_type is None``
  are not shardable from ARG and are silently skipped by the factory.

What this cut ships (Step 3d)
-----------------------------

- Bearer-token authenticated ``POST`` against the ARG REST endpoint under
  a bounded per-request timeout.
- ``$skipToken`` pagination — the loop halts on an empty token or an empty
  ``data`` page.
- Response → :class:`ResourceRecord` mapping (``resource_id`` = CSP-neutral
  path; ``provider_ref`` = raw ARM id; ``props`` carries a length-bounded
  subset of the ARG row).
- **``contains`` link extraction** from the ARM id hierarchy: every
  resource inside a resource-group emits a ``contains(rg, resource)``
  edge. Purely a function of the ARM id — never reads untrusted vendor
  ``properties`` for this — so the blast-radius seam has a real edge
  set without a trust boundary.
- **``attached_to`` link extraction** from a narrow whitelist of
  well-known ``properties`` paths (``subnet.id`` /
  ``networkSecurityGroup.id`` / ``publicIPAddress.id``). The referenced
  target's CSP-neutral ``resource_type`` is resolved through the
  vocabulary's ``azure_arm_type`` reverse map; targets whose ARM type
  is not in the vocabulary are dropped rather than emitted with an
  unknown ``to_type``.
- **``depends_on`` link extraction** from a separate soft-dependency
  whitelist (``storageAccount.id`` / ``workspaceResourceId`` /
  ``acrLoginServer``). The first two carry ARM ids and resolve through
  the same reverse map as ``attached_to``; ``acrLoginServer`` is a DNS
  name that requires a login-server → ARM id registry lookup and is
  skipped when the resolver cannot map it (the current default —
  positive resolution lands when the ACR registry is wired).

Safety / cost invariants
------------------------

- **Bounded pagination**: :attr:`AzureArgQueryFactoryConfig.max_pages` caps
  the number of ``$skipToken`` follows so a runaway subscription cannot
  starve the event loop.
- **Bounded record size**: property maps are truncated at
  :attr:`AzureArgQueryFactoryConfig.max_props_bytes` to keep untrusted
  vendor properties inert.
- **Fail-closed on partial**: a non-2xx response or a malformed page
  raises :class:`ArgQueryError`. The
  :class:`~aiopspilot.delivery.azure.inventory.AzureResourceGraphInventory`
  cancels outstanding shards and skips the ``final=True`` fence, so the
  caller retains the previous graph — matches ``csp-neutrality.md § 5``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import httpx

from aiopspilot.delivery.azure.inventory import ResourceQueryFn
from aiopspilot.rule_catalog.schema.resource_type import ResourceTypeRegistry
from aiopspilot.shared.providers.inventory import LinkRecord, ResourceRecord
from aiopspilot.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ARG_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_ARG_API_VERSION: Final[str] = "2022-10-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_DEFAULT_PAGE_SIZE: Final[int] = 1000
_DEFAULT_MAX_PAGES: Final[int] = 32
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_MAX_PROPS_BYTES: Final[int] = 64 * 1024


class ArgQueryError(RuntimeError):
    """Raised when an ARG shard query fails or returns unusable output.

    The message is safe to log — it never carries raw response bodies or
    tenant-identifying values, only the failing shard's resource_type,
    HTTP status, and a short-truncated reason string.
    """


@dataclass(frozen=True, slots=True)
class AzureArgQueryFactoryConfig:
    """Configuration for the ARG query factory.

    Every value has a documented default so the composition root
    only needs to supply what a fork wants to override.
    """

    subscription_scopes: tuple[str, ...]
    """Subscription (or management-group) ids the ARG query runs over.

    MUST NOT be empty; ARG rejects the request when no scope is supplied,
    and an empty scope is almost always an environment-loading bug.
    """

    arg_endpoint: str = _DEFAULT_ARG_ENDPOINT
    """Root URL for the ARM control plane; ``azure-china`` / ``us-gov`` clouds override this."""

    arg_api_version: str = _DEFAULT_ARG_API_VERSION
    """ARG REST API version.

    Pinned by the adapter, not the SDK — a version bump is an intentional,
    reviewable change (contract diff), never a mid-flight upgrade.
    """

    audience: str = _DEFAULT_AUDIENCE
    """OIDC audience the executor requests from :class:`WorkloadIdentity`."""

    page_size: int = _DEFAULT_PAGE_SIZE
    """ARG `$top` value; the API caps this at 1000."""

    max_pages: int = _DEFAULT_MAX_PAGES
    """Upper bound on ``$skipToken`` follow-ups per shard.

    Ceiling defense against a runaway result set. Exceeding it raises
    :class:`ArgQueryError` — the caller retries with a narrower query
    rather than silently truncating.
    """

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    """Per-HTTP-request timeout applied to every page fetch."""

    max_props_bytes: int = _DEFAULT_MAX_PROPS_BYTES
    """Cap on the serialized size of the untrusted ``props`` map per record.

    Vendor properties (tags, descriptions) are inert data and MUST be
    length-bounded before they flow into the ontology graph.
    """


class AzureArgQueryFactory:
    """Build a :type:`ResourceQueryFn` bound to a WorkloadIdentity + HTTP client."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        resource_types: ResourceTypeRegistry,
        http_client: httpx.AsyncClient,
        config: AzureArgQueryFactoryConfig,
    ) -> None:
        if not config.subscription_scopes:
            raise ValueError("AzureArgQueryFactoryConfig.subscription_scopes MUST NOT be empty")
        if config.page_size < 1 or config.page_size > 1000:
            raise ValueError("page_size MUST be in [1, 1000]")
        if config.max_pages < 1:
            raise ValueError("max_pages MUST be >= 1")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if config.max_props_bytes < 1024:
            raise ValueError("max_props_bytes MUST be >= 1024")

        self._identity: Final[WorkloadIdentity] = identity
        self._resource_types: Final[ResourceTypeRegistry] = resource_types
        self._http: Final[httpx.AsyncClient] = http_client
        self._config: Final[AzureArgQueryFactoryConfig] = config
        # Pre-compute the ARM-type → neutral-id reverse map once. Every
        # `attached_to` extraction hits this map per referenced id; a
        # fresh iteration per row would be O(vocabulary_size * rows).
        self._arm_to_neutral: Final[Mapping[str, str]] = _build_arm_to_neutral_map(resource_types)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_query_fn(self) -> ResourceQueryFn:
        """Return a :type:`ResourceQueryFn` closed over this factory's state."""

        async def _fetch(
            resource_type: str,
        ) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
            arm_type = self._resolve_arm_type(resource_type)
            if arm_type is None:
                # The vocabulary does not declare an ARM path for this
                # CSP-neutral type — nothing to fetch from Azure. This is
                # a legitimate no-op, not an error (e.g. a future
                # `secret-store` variant with no direct ARM equivalent).
                return (), ()

            resources, attached_links = await self._fetch_all_pages(
                resource_type=resource_type, arm_type=arm_type
            )
            contains_links = _extract_rg_contains_links(resources)
            return resources, (*contains_links, *attached_links)

        return _fetch

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_arm_type(self, resource_type: str) -> str | None:
        try:
            entry = self._resource_types.get(resource_type)
        except KeyError:
            # Unknown resource_type is a caller bug, not our concern here;
            # the Inventory shard set comes from the same vocabulary.
            raise ArgQueryError(
                f"unknown resource_type {resource_type!r} (not in vocabulary)"
            ) from None
        return entry.azure_arm_type

    def _build_query(self, *, arm_type: str) -> str:
        # Kusto: quote the arm_type as a case-insensitive equality; project
        # only the fields the mapper reads. Adding fields is a versioned
        # change, not an ad-hoc query mutation.
        # `arm_type` is enum-constrained via ResourceTypeRegistry so a
        # quote-escape isn't reachable, but we still guard by rejecting
        # any embedded single-quote at the boundary.
        if "'" in arm_type:
            raise ArgQueryError(f"illegal character in ARM type {arm_type!r}")
        return (
            f"Resources | where type =~ '{arm_type}' "
            "| project id, type, name, location, tags, properties, resourceGroup, subscriptionId"
        )

    async def _fetch_all_pages(
        self, *, resource_type: str, arm_type: str
    ) -> tuple[tuple[ResourceRecord, ...], tuple[LinkRecord, ...]]:
        query = self._build_query(arm_type=arm_type)
        url = (
            f"{self._config.arg_endpoint.rstrip('/')}"
            "/providers/Microsoft.ResourceGraph/resources"
            f"?api-version={self._config.arg_api_version}"
        )

        token = await self._identity.get_token(self._config.audience)
        headers = {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        collected: list[ResourceRecord] = []
        collected_links: list[LinkRecord] = []
        skip_token: str | None = None

        for page in range(self._config.max_pages):
            body: dict[str, Any] = {
                "subscriptions": list(self._config.subscription_scopes),
                "query": query,
                "options": {"$top": self._config.page_size},
            }
            if skip_token is not None:
                body["options"]["$skipToken"] = skip_token

            try:
                response = await self._http.post(
                    url,
                    headers=headers,
                    content=json.dumps(body),
                    timeout=self._config.timeout_seconds,
                )
            except httpx.HTTPError as exc:
                raise ArgQueryError(
                    f"ARG request failed for {resource_type!r} (page {page}): {exc}"
                ) from exc

            if response.status_code >= 400:
                # Truncate the body so a huge error page does not blow up
                # the audit log. Body content is untrusted vendor text.
                snippet = response.text[:200].replace("\n", " ")
                raise ArgQueryError(
                    f"ARG returned HTTP {response.status_code} for {resource_type!r} "
                    f"(page {page}): {snippet!r}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise ArgQueryError(
                    f"ARG returned non-JSON for {resource_type!r} (page {page})"
                ) from exc

            data = payload.get("data")
            if not isinstance(data, list):
                raise ArgQueryError(
                    f"ARG payload missing 'data' array for {resource_type!r} (page {page})"
                )

            for row in data:
                if not isinstance(row, Mapping):
                    continue
                record = self._map_row(row, resource_type=resource_type)
                if record is not None:
                    collected.append(record)
                    # Extract attached_to links from the untruncated row
                    # (props truncation happens inside _map_row and could
                    # otherwise drop the referenced ids).
                    collected_links.extend(
                        _extract_attached_to_links_from_row(
                            row, child=record, arm_to_neutral=self._arm_to_neutral
                        )
                    )
                    collected_links.extend(
                        _extract_depends_on_links_from_row(
                            row, child=record, arm_to_neutral=self._arm_to_neutral
                        )
                    )

            next_token = payload.get("$skipToken")
            if not isinstance(next_token, str) or not next_token:
                break
            skip_token = next_token
        else:
            # Loop ran to max_pages without breaking → pagination cap hit.
            raise ArgQueryError(
                f"ARG pagination cap ({self._config.max_pages}) exceeded for {resource_type!r}; "
                "narrow the query or raise max_pages via config"
            )

        return tuple(collected), tuple(collected_links)

    def _map_row(self, row: Mapping[str, Any], *, resource_type: str) -> ResourceRecord | None:
        arm_id = row.get("id")
        if not isinstance(arm_id, str) or not arm_id:
            return None

        neutral_id = _to_neutral_id(arm_id)
        props: dict[str, Any] = {}
        for key in ("name", "location", "tags", "properties", "resourceGroup"):
            if key in row and row[key] is not None:
                props[key] = row[key]

        props = _truncate_props(props, max_bytes=self._config.max_props_bytes)

        return ResourceRecord(
            resource_id=neutral_id,
            type=resource_type,
            props=props,
            provider_ref=arm_id,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_RESOURCE_GROUP_TYPE: Final[str] = "resource-group"


def _to_neutral_id(arm_id: str) -> str:
    """Fold the ARM path into a CSP-neutral resource identifier.

    The ontology's ``resource_id`` is defined as a stable, non-vendor path
    keyed on tenancy scope + resource name (docs/roadmap/llm-strategy.md
    § Ontology Foundation). For P1 we adopt a conservative rule: strip the
    leading ``/subscriptions/...`` prefix and lowercase — enough for the
    audit log to link ontology → provider, without leaking ARM.
    Later phases MAY refine this once the ontology promotes ``tenancy``
    to a first-class field.
    """
    trimmed = arm_id.strip()
    # ARM ids start with `/subscriptions/<guid>/resourceGroups/<name>/...`
    marker = "/resourceGroups/"
    idx = trimmed.lower().find(marker.lower())
    if idx == -1:
        return trimmed.lower()
    return f"resource-group{trimmed[idx + len(marker) - len('/') :].lower()}"


def _truncate_props(props: Mapping[str, Any], *, max_bytes: int) -> dict[str, Any]:
    """Cap the JSON-serialized size of ``props`` so untrusted vendor data stays inert."""
    encoded = json.dumps(props, default=str, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= max_bytes:
        # Round-trip through JSON to normalise types (dates → strings).
        return dict(json.loads(encoded))

    # Drop the widest offender first — usually `properties` (nested dict).
    # Truncation is best-effort; the record still carries the ARM id via
    # `provider_ref`, so an operator can retrieve full detail out-of-band.
    trimmed = dict(props)
    for key in ("properties", "tags"):
        trimmed.pop(key, None)
        rerun = json.dumps(trimmed, default=str, ensure_ascii=False, separators=(",", ":"))
        if len(rerun.encode("utf-8")) <= max_bytes:
            result = dict(json.loads(rerun))
            result["_truncated"] = True
            return result

    return {"_truncated": True, "resource_id_hint": props.get("name")}


def _extract_rg_contains_links(
    resources: Sequence[ResourceRecord],
) -> tuple[LinkRecord, ...]:
    """Emit one ``contains(resource-group, resource)`` edge per RG-scoped resource.

    Purely a function of the ARM id (via ``provider_ref``) — never
    reads ``props`` — so the trust boundary from vendor properties
    stays intact. A resource without ``provider_ref`` (rare; the mapper
    always sets it, but a hand-crafted fixture might not) is skipped.

    Deduplication is by the standard link key
    ``(from_id, link_type, to_id)`` — repeats within one shard collapse
    into a single edge, matching the ``LinkRecord`` idempotency contract
    on :class:`~aiopspilot.shared.providers.inventory.InventoryBatch`.

    The Resource-Group node itself is emitted implicitly through the
    edge's ``from_id`` — the resource-group ``ResourceRecord`` MAY or
    MAY NOT appear in the same shard (the caller's shard set decides).
    That is fine: the ingest layer stores links whose endpoints may
    predate observation of the referenced node.
    """
    rg_marker = "/resourceGroups/"
    seen: set[tuple[str, str, str]] = set()
    links: list[LinkRecord] = []
    for record in resources:
        arm_id = record.provider_ref
        if not arm_id:
            continue
        marker_idx = arm_id.lower().find(rg_marker.lower())
        if marker_idx == -1:
            continue
        # Locate the segment immediately after the RG name; the parent
        # RG's ARM id ends there. Guards against `contains(rg, rg)`
        # self-edges when scanning the resource-group type itself.
        after_marker = marker_idx + len(rg_marker)
        next_slash = arm_id.find("/", after_marker)
        if next_slash == -1:
            # The resource IS a resource-group (arm_id ends after the
            # RG name). No parent to emit — that edge lives on the
            # subscription level, out of P1 scope.
            continue
        rg_arm_id = arm_id[:next_slash]
        rg_neutral_id = _to_neutral_id(rg_arm_id)
        key = (rg_neutral_id, "contains", record.resource_id)
        if key in seen:
            continue
        seen.add(key)
        links.append(
            LinkRecord(
                from_id=rg_neutral_id,
                from_type=_RESOURCE_GROUP_TYPE,
                link_type="contains",
                to_id=record.resource_id,
                to_type=record.type,
            )
        )
    return tuple(links)


# Well-known top-level `properties.<key>.id` paths that carry ARM ids to
# a referenced resource. Deliberately narrow so a change here is a
# reviewable, versioned expansion — never a wildcard walk of untrusted
# vendor data.
_ATTACHED_TO_PROPERTY_KEYS: Final[tuple[str, ...]] = (
    "subnet",
    "networkSecurityGroup",
    "publicIPAddress",
)


def _build_arm_to_neutral_map(registry: ResourceTypeRegistry) -> dict[str, str]:
    """Reverse ``ResourceTypeRegistry.get(id).azure_arm_type`` lookup.

    Case-insensitive matching — ARM type spellings occasionally drift
    (`Microsoft.Storage/storageAccounts` vs
    `microsoft.storage/storageaccounts` on legacy events); the map keys
    are lowered and the callers lowercase their inputs.
    """
    out: dict[str, str] = {}
    for entry in registry:
        if entry.azure_arm_type is None:
            continue
        out[entry.azure_arm_type.lower()] = entry.id
    return out


def _arm_id_to_type(arm_id: str) -> str | None:
    """Extract the ``Microsoft.X/Y[/Z]`` type suffix from a full ARM id.

    Handles the multi-segment case (``.../providers/Microsoft.Network/
    virtualNetworks/vnet1/subnets/sub1`` → ``Microsoft.Network/
    virtualNetworks/subnets``). Returns ``None`` when the id does not
    have a ``/providers/`` segment.
    """
    marker = "/providers/"
    idx = arm_id.find(marker)
    if idx == -1:
        return None
    parts = arm_id[idx + len(marker) :].split("/")
    if len(parts) < 2:
        return None
    # parts = [namespace, primary_type, name, sub_type, sub_name, ...]
    # Rebuild the type path by taking every OTHER segment starting at
    # index 1: namespace/primary/sub1/sub2/...
    provider = parts[0]
    type_segments: list[str] = []
    # parts pattern after provider: [type_a, name_a, type_b, name_b, ...]
    for i in range(1, len(parts), 2):
        type_segments.append(parts[i])
    if not type_segments:
        return None
    return f"{provider}/{'/'.join(type_segments)}"


def _extract_attached_to_links_from_row(
    row: Mapping[str, Any],
    *,
    child: ResourceRecord,
    arm_to_neutral: Mapping[str, str],
) -> tuple[LinkRecord, ...]:
    """Walk the whitelisted ``properties.<key>.id`` paths.

    Emits one ``attached_to(child, target)`` per resolvable reference:

    - The referenced value MUST be a non-empty string ARM id.
    - The referenced ARM type MUST be in the vocabulary's reverse map;
      unmapped targets are dropped (safer than emitting an unknown
      ``to_type`` that the ontology would reject at ingest).
    - Duplicates within one row collapse into a single edge.
    """
    properties = row.get("properties")
    if not isinstance(properties, Mapping):
        return ()

    seen: set[tuple[str, str, str]] = set()
    links: list[LinkRecord] = []
    for key in _ATTACHED_TO_PROPERTY_KEYS:
        nested = properties.get(key)
        if not isinstance(nested, Mapping):
            continue
        ref_id = nested.get("id")
        if not isinstance(ref_id, str) or not ref_id:
            continue
        arm_type = _arm_id_to_type(ref_id)
        if arm_type is None:
            continue
        to_type = arm_to_neutral.get(arm_type.lower())
        if to_type is None:
            continue
        target_neutral = _to_neutral_id(ref_id)
        dedup_key = (child.resource_id, "attached_to", target_neutral)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        links.append(
            LinkRecord(
                from_id=child.resource_id,
                from_type=child.type,
                link_type="attached_to",
                to_id=target_neutral,
                to_type=to_type,
            )
        )
    return tuple(links)


# Well-known `properties.<key>` paths that carry a **soft** dependency —
# the child cannot function without the target but is not part of its
# lifecycle (contrast with `contains`). Deliberately narrow so a change
# here is a reviewable, versioned expansion — never a wildcard walk of
# untrusted vendor data.
#
# Two shapes are supported:
#
# 1. Nested ARM-id: `properties.<key>.id` (matches the `attached_to`
#    shape) — currently used by App Service / Function / AKS storage
#    account references.
# 2. Top-level ARM-id string: `properties.<key>` (Diagnostic Settings
#    `workspaceResourceId` and similar).
#
# `properties.acrLoginServer` is a DNS name, not an ARM id; resolving
# it back to a registry ARM id needs a separate login-server → ARM id
# lookup that is not wired in this cycle. The code recognises the key
# and short-circuits ("skip if not resolvable") so the whitelist stays
# authoritative while the resolver lands in a follow-up cycle.
_DEPENDS_ON_ID_PROPERTY_KEYS: Final[tuple[str, ...]] = ("storageAccount",)
_DEPENDS_ON_ARM_ID_STRING_KEYS: Final[tuple[str, ...]] = ("workspaceResourceId",)


def _resolve_acr_login_server_to_arm_id(login_server: str) -> str | None:
    """Placeholder for the ACR login-server → ARM id registry lookup.

    Returns ``None`` in this cycle — no resolver is wired yet, so every
    ``properties.acrLoginServer`` reference is treated as unresolvable
    and dropped by :func:`_extract_depends_on_links_from_row`. Tests
    monkeypatch this hook to exercise the resolvable path when the
    registry lookup is wired.
    """
    # `login_server` is untrusted vendor text; the guard here is
    # intentionally boring so it stays inert.
    del login_server
    return None


def _extract_depends_on_links_from_row(
    row: Mapping[str, Any],
    *,
    child: ResourceRecord,
    arm_to_neutral: Mapping[str, str],
) -> tuple[LinkRecord, ...]:
    """Walk the whitelisted soft-dependency property paths.

    Emits one ``depends_on(child, target)`` per resolvable reference:

    - ``properties.storageAccount.id`` (nested ARM id) — App Service /
      Function / AKS → storage.
    - ``properties.workspaceResourceId`` (top-level ARM id string) —
      Diagnostic Setting → log-workspace.
    - ``properties.acrLoginServer`` (top-level DNS string) — resolved
      back to an ARM id via
      :func:`_resolve_acr_login_server_to_arm_id`; dropped when the
      resolver returns ``None`` (the current default).

    Same safety envelope as :func:`_extract_attached_to_links_from_row`:

    - The referenced value MUST be a non-empty string ARM id.
    - The referenced ARM type MUST be in the vocabulary's reverse map;
      unmapped targets are dropped (safer than emitting an unknown
      ``to_type`` that the ontology would reject at ingest).
    - Duplicates within one row (across all whitelisted paths) collapse
      into a single edge — matches the ``LinkRecord`` idempotency
      contract on :class:`~aiopspilot.shared.providers.inventory.InventoryBatch`.
    """
    properties = row.get("properties")
    if not isinstance(properties, Mapping):
        return ()

    seen: set[tuple[str, str, str]] = set()
    links: list[LinkRecord] = []

    def _try_emit(ref_id: str) -> None:
        arm_type = _arm_id_to_type(ref_id)
        if arm_type is None:
            return
        to_type = arm_to_neutral.get(arm_type.lower())
        if to_type is None:
            return
        target_neutral = _to_neutral_id(ref_id)
        dedup_key = (child.resource_id, "depends_on", target_neutral)
        if dedup_key in seen:
            return
        seen.add(dedup_key)
        links.append(
            LinkRecord(
                from_id=child.resource_id,
                from_type=child.type,
                link_type="depends_on",
                to_id=target_neutral,
                to_type=to_type,
            )
        )

    # 1. Nested `properties.<key>.id` references.
    for key in _DEPENDS_ON_ID_PROPERTY_KEYS:
        nested = properties.get(key)
        if not isinstance(nested, Mapping):
            continue
        ref_id = nested.get("id")
        if not isinstance(ref_id, str) or not ref_id:
            continue
        _try_emit(ref_id)

    # 2. Top-level `properties.<key>` ARM-id string references.
    for key in _DEPENDS_ON_ARM_ID_STRING_KEYS:
        ref_id = properties.get(key)
        if not isinstance(ref_id, str) or not ref_id:
            continue
        _try_emit(ref_id)

    # 3. `properties.acrLoginServer` — DNS-name string requiring a
    # separate registry lookup. Skip when the resolver cannot map the
    # login-server back to an ARM id (the current default).
    login_server = properties.get("acrLoginServer")
    if isinstance(login_server, str) and login_server:
        resolved = _resolve_acr_login_server_to_arm_id(login_server)
        if resolved is not None:
            _try_emit(resolved)

    return tuple(links)


# Guard against accidental widening: this file MUST NOT introduce
# `azure-mgmt-*` imports. The single dependency is `httpx`.


__all__ = [
    "ArgQueryError",
    "AzureArgQueryFactory",
    "AzureArgQueryFactoryConfig",
]
