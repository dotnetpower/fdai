"""Azure Resource Graph (ARG) implementation of the ``Inventory`` Protocol.

This module realizes the 5th CSP-neutral wire contract for Azure - see
``docs/roadmap/architecture/csp-neutrality.md § 5. Inventory Contract`` and the Protocol
in ``services/core-control-plane/src/fdai/shared/providers/inventory.py``.

P1 W-2 scope (stub)
-------------------

The **structural contract** is frozen here so downstream consumers (the
T0 engine's future graph-derived blast-radius, and the risk-gate) can be
wired against a real interface:

- **Parallel full-scan**: :meth:`AzureResourceGraphInventory.full_snapshot`
  shards work by ``resource_type`` under a **bounded semaphore**
  (``max_concurrent_queries``, default 4). The stub uses a synthetic
  ``ResourceQueryFn`` so tests can assert the concurrency structure without
  standing up ARG.
- **Atomic-promote fence**: the stream **always** ends with an
  :class:`InventoryBatch` whose ``final=True``. A caller MUST discard a
  stream that ends without it; the stub enforces this on every path.
- **Progress heartbeat**: an empty non-final batch claims no graph evidence.
    ``full_snapshot`` emits one as each bounded provider read completes so a
    consumer can distinguish a slow scan from a stalled one.
- **Idempotent upsert (interface)**: batches are keyed on
  ``resource_id`` for resources and ``(from_id, link_type, to_id)`` for
  links. Adapters MUST NOT emit duplicates within one snapshot - this
  stub deduplicates the synthetic input to make the invariant testable.
- **Delta stream**: :meth:`AzureResourceGraphInventory.delta` accepts a
  cursor and, when an :type:`ActivityLogFetchFn` is bound, pages the
  forwarded Azure Activity Log change stream into idempotent-upsert
  batches with an advancing cursor and the same ``final=True`` fence.
  With no fetch bound it returns an empty final batch (the default until
  the forwarder ships). The Activity-Log-to-Kafka forwarding is a
  deployment concern (Event Hubs diagnostic settings); the neutral
  mapping "one Activity Log record -> one :class:`ResourceRecord` upsert"
  lives in
  :class:`~fdai.delivery.azure.activity_log.AzureActivityLogFactory`.

What is deliberately NOT here yet
---------------------------------

- No ``azure-mgmt-resourcegraph`` client is instantiated (that lands in
  P1 W-3 together with the OIDC-federated ``WorkloadIdentity`` binding).
- No Kusto query templates ship - they are configuration, not code.
- No writes into ``ontology_resource`` / ``ontology_link``; the caller
  (event-ingest) is the upsert authority per the Inventory contract.
- No Azure SDK imports appear anywhere in the module tree yet. When they
  land they stay confined to this file (or a sibling under
  ``delivery/azure/``) - ``core/`` never imports them.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Final

from fdai.shared.providers.inventory import (
    UNCLASSIFIED_RESOURCE_TYPE,
    InventoryBatch,
    LinkRecord,
    ProviderScopeCoverage,
    RelationshipDrop,
    RelationshipDropReason,
    ResourceRecord,
)

_DEFAULT_MAX_CONCURRENT_QUERIES: Final[int] = 4
_DEFAULT_MAX_DELTA_PAGES: Final[int] = 64


# Injected async callable: given a resource_type, return the batch of
# resources + links the adapter would have fetched from ARG for that
# shard. Kept as a Protocol-like callable so tests can supply a fake
# without instantiating any Azure client.
@dataclass(frozen=True, slots=True)
class ResourceQueryResult:
    """One ARG shard result with relationship suppression evidence."""

    resources: tuple[ResourceRecord, ...] = ()
    links: tuple[LinkRecord, ...] = ()
    relationship_drops: tuple[RelationshipDrop, ...] = ()

    def __iter__(self) -> Iterator[Sequence[ResourceRecord] | Sequence[LinkRecord]]:
        """Preserve the legacy ``resources, links = result`` adapter contract."""

        yield self.resources
        yield self.links


ResourceQueryFn = Callable[
    [str],
    Awaitable[ResourceQueryResult | tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]],
]
ScopeCoverageFn = Callable[[], Awaitable[ProviderScopeCoverage]]
UnmappedResourceQueryFn = Callable[[], Awaitable[ResourceQueryResult]]


@dataclass(frozen=True, slots=True)
class ActivityLogPage:
    """One page of forwarded Azure Activity Log changes, already mapped to
    CSP-neutral records.

    Produced by the injected :type:`ActivityLogFetchFn` - the "how do I
    read the Activity-Log-on-Kafka topic (or the Activity Log REST API)
    and normalize it" concern lives in the fetch function (see
    :class:`~fdai.delivery.azure.activity_log.AzureActivityLogFactory`),
    never in the inventory adapter. ``cursor`` is the opaque position the
    adapter echoes back on the next :meth:`AzureResourceGraphInventory.delta`
    call; ``has_more`` drives the adapter's bounded page loop.
    """

    resources: tuple[ResourceRecord, ...] = ()
    links: tuple[LinkRecord, ...] = ()
    cursor: str | None = None
    has_more: bool = False
    relationship_reconciliation_after: str | None = None
    """Newest tracked write/delete whose complete links require an ARG snapshot."""


# Injected async callable for the incremental path: given the current
# cursor, return the next page of forwarded Activity Log changes. A fork
# binds a Kafka-consumer- or REST-backed implementation at the composition
# root; tests supply a fake without standing up Event Hubs.
ActivityLogFetchFn = Callable[[str], Awaitable[ActivityLogPage]]


@dataclass(frozen=True, slots=True)
class AzureInventoryConfig:
    """Adapter configuration.

    Values come from :class:`fdai.shared.config.AppConfig` at the
    composition root; nothing here is hard-coded per environment.
    """

    resource_types: tuple[str, ...]
    """Which CSP-neutral ``resource_type`` values to shard the full-scan on.

    Sourced from the canonical vocabulary
    (``rule-catalog/vocabulary/resource-types.yaml``) - a fork narrows
    this list at deploy time to scope the initial scan.
    """

    max_concurrent_queries: int = _DEFAULT_MAX_CONCURRENT_QUERIES
    """Upper bound on concurrent ARG queries during ``full_snapshot``.

    A large tenant must not exhaust the ARG budget;
    ``docs/roadmap/architecture/csp-neutrality.md § 5`` requires bounded
    concurrency for the parallel scan.
    """

    subscription_scopes: tuple[str, ...] = field(default_factory=tuple)
    """Subscription (or management-group) scopes the ARG queries run under.

    Empty tuple means "single scope resolved from the injected
    :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`
    binding at query time" - the adapter never reads a subscription id
    from an environment variable directly.
    """

    max_delta_pages: int = _DEFAULT_MAX_DELTA_PAGES
    """Upper bound on Activity-Log pages consumed per :meth:`delta` call.

    Ceiling defense against a runaway change stream starving the event
    loop. When the fetch reports ``has_more`` past this cap, :meth:`delta`
    stops and returns the ``final=True`` fence carrying the last cursor;
    the next call resumes from there rather than silently draining forever.
    """


class AzureResourceGraphInventory:
    """Azure Resource Graph ``Inventory`` adapter (sharded full-scan).

    Implements the :class:`Inventory` Protocol over an injected
    :type:`ResourceQueryFn`. The live query function is produced by
    :class:`~fdai.delivery.azure.arg_query.AzureArgQueryFactory` and wired
    at the composition root through
    :func:`fdai.composition.bind_azure_inventory`; tests inject a synthetic
    ``ResourceQueryFn`` to assert the concurrency structure and
    atomic-promote fence without standing up ARG. The ``full_snapshot``
    path is live once bound; the ``delta`` (Activity-Log -> Kafka) path is
    still a stub until the forwarder ships (see ``csp-neutrality.md § 5``).
    """

    def __init__(
        self,
        *,
        config: AzureInventoryConfig,
        query: ResourceQueryFn,
        scope_coverage: ScopeCoverageFn | None = None,
        unmapped_resources: UnmappedResourceQueryFn | None = None,
        delta_fetch: ActivityLogFetchFn | None = None,
    ) -> None:
        if config.max_concurrent_queries < 1:
            raise ValueError("AzureInventoryConfig.max_concurrent_queries MUST be >= 1")
        if config.max_delta_pages < 1:
            raise ValueError("AzureInventoryConfig.max_delta_pages MUST be >= 1")
        if unmapped_resources is not None and scope_coverage is None:
            raise ValueError("unmapped_resources requires scope_coverage")
        self._config = config
        self._query = query
        self._scope_coverage = scope_coverage
        self._unmapped_resources = unmapped_resources
        self._delta_fetch = delta_fetch

    # ------------------------------------------------------------------
    # Inventory Protocol
    # ------------------------------------------------------------------

    async def full_snapshot(self, since: str | None = None) -> AsyncIterator[InventoryBatch]:
        """Parallel full-scan, sharded by ``resource_type``.

        Validates and combines all completed shards into one generation
        :class:`InventoryBatch`, then emits a final ``final=True`` fence
        batch the caller uses to atomically promote the new graph
        (``docs/roadmap/architecture/csp-neutrality.md § 5``).

        ``since`` is currently unused - the stub returns the full shard
        each call. Production may honor it as an ``since <= last_seen``
        optimization; it MUST NOT substitute for :meth:`delta`.
        """
        del since  # reserved (see docstring)

        semaphore = asyncio.Semaphore(self._config.max_concurrent_queries)

        async def _fetch(rt: str) -> InventoryBatch:
            async with semaphore:
                query_result = await self._query(rt)
            resources_raw: Sequence[ResourceRecord]
            links_raw: Sequence[LinkRecord]
            relationship_drops: tuple[RelationshipDrop, ...]
            if isinstance(query_result, ResourceQueryResult):
                resources_raw = query_result.resources
                links_raw = query_result.links
                relationship_drops = query_result.relationship_drops
            else:
                resources_raw, links_raw = query_result
                relationship_drops = ()
            resources = _dedupe_resources(resources_raw)
            links, duplicate_drops = _validate_links(links_raw)
            return InventoryBatch(
                resources=resources,
                links=links,
                relationship_drops=(*relationship_drops, *duplicate_drops),
            )

        tasks = [
            asyncio.create_task(_fetch(rt), name=f"arg-shard-{rt}")
            for rt in self._config.resource_types
        ]
        coverage_task: asyncio.Task[ProviderScopeCoverage] | None = None
        scope_coverage = self._scope_coverage
        if scope_coverage is not None:

            async def _fetch_coverage() -> ProviderScopeCoverage:
                async with semaphore:
                    return await scope_coverage()

            coverage_task = asyncio.create_task(
                _fetch_coverage(),
                name="inventory-provider-scope-coverage",
            )
        unmapped_task: asyncio.Task[ResourceQueryResult] | None = None
        unmapped_resources = self._unmapped_resources
        if unmapped_resources is not None:

            async def _fetch_unmapped_resources() -> ResourceQueryResult:
                async with semaphore:
                    return await unmapped_resources()

            unmapped_task = asyncio.create_task(
                _fetch_unmapped_resources(),
                name="inventory-unclassified-provider-resources",
            )
        all_tasks: list[asyncio.Task[object]] = [*tasks]
        if coverage_task is not None:
            all_tasks.append(coverage_task)
        if unmapped_task is not None:
            all_tasks.append(unmapped_task)

        try:
            completed: list[InventoryBatch] = []
            for coro in asyncio.as_completed(tasks):
                completed.append(await coro)
                yield InventoryBatch()
            provider_scope_coverage = await coverage_task if coverage_task is not None else None
            if coverage_task is not None:
                yield InventoryBatch()
            if unmapped_task is not None:
                if provider_scope_coverage is None:
                    raise RuntimeError("unclassified resources require provider scope coverage")
                unmapped_batch, provider_scope_coverage = _reconcile_unmapped_resources(
                    await unmapped_task,
                    provider_scope_coverage,
                )
                if (
                    unmapped_batch.resources
                    or unmapped_batch.links
                    or unmapped_batch.relationship_drops
                ):
                    completed.append(unmapped_batch)
                yield InventoryBatch()
        except BaseException:
            # Fail-closed: cancel outstanding shards so a partial snapshot
            # never quietly lands. The caller retains the previous graph
            # because we never yielded a `final=True` batch. Await the
            # cancels so shard sockets close before the exception unwinds
            # past our generator - otherwise aiohttp / httpx warn about
            # unfinished coroutines on shutdown.
            for t in all_tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*all_tasks, return_exceptions=True)
            raise

        resources = _dedupe_resources(
            resource for batch in completed for resource in batch.resources
        )
        links, generation_drops = _validate_links(
            link for batch in completed for link in batch.links
        )
        relationship_drops = (
            tuple(drop for batch in completed for drop in batch.relationship_drops)
            + generation_drops
        )
        if resources or links or relationship_drops:
            yield InventoryBatch(
                resources=resources,
                links=links,
                relationship_drops=relationship_drops,
            )

        yield InventoryBatch(
            final=True,
            provider_scope_coverage=provider_scope_coverage,
        )

    async def delta(self, cursor: str) -> AsyncIterator[InventoryBatch]:
        """Incremental change stream from forwarded Azure Activity Log entries.

        When a :type:`ActivityLogFetchFn` is bound, this pages the change
        stream starting at ``cursor``: each page is mapped to an
        :class:`InventoryBatch` of idempotent upserts (keyed on
        ``resource_id`` / ``(from_id, link_type, to_id)``) carrying the
        page cursor, and the stream ends with a ``final=True`` fence
        carrying the last cursor so the caller can atomically advance.

        Fail-closed on partial: if a page fetch raises, the exception
        propagates **without** a ``final=True`` fence, so the caller keeps
        the previous cursor and retries rather than banking a truncated
        delta (matches ``csp-neutrality.md § 5``).

        With no fetch bound (the default until the Activity-Log forwarder
        ships), this yields a single ``final=True`` empty batch so callers
        exercise the same atomic-promote fence as ``full_snapshot``.
        """
        if self._delta_fetch is None:
            del cursor
            yield InventoryBatch(final=True)
            return

        current = cursor
        pages = 0
        while pages < self._config.max_delta_pages:
            page = await self._delta_fetch(current)
            pages += 1
            if page.has_more and (not page.cursor or page.cursor == current):
                raise RuntimeError("inventory delta continuation cursor did not advance")
            resources = _dedupe_resources(page.resources)
            links, relationship_drops = _validate_links(page.links)
            if (
                resources
                or links
                or relationship_drops
                or page.relationship_reconciliation_after is not None
            ):
                yield InventoryBatch(
                    resources=resources,
                    links=links,
                    relationship_drops=relationship_drops,
                    cursor=page.cursor,
                    relationship_reconciliation_after=page.relationship_reconciliation_after,
                )
            if page.cursor is not None:
                current = page.cursor
            if not page.has_more:
                break

        yield InventoryBatch(final=True, cursor=current)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dedupe_resources(records: Iterable[ResourceRecord]) -> tuple[ResourceRecord, ...]:
    seen: dict[str, ResourceRecord] = {}
    for record in records:
        existing = seen.get(record.resource_id)
        if existing is not None and existing != record:
            raise RuntimeError(
                f"inventory resource {record.resource_id!r} has conflicting duplicates"
            )
        seen[record.resource_id] = record
    return tuple(seen[key] for key in sorted(seen))


def _validate_links(
    records: Iterable[LinkRecord],
) -> tuple[tuple[LinkRecord, ...], tuple[RelationshipDrop, ...]]:
    seen: dict[tuple[str, str, str], list[LinkRecord]] = {}
    for record in records:
        seen.setdefault((record.from_id, record.link_type, record.to_id), []).append(record)
    links: list[LinkRecord] = []
    drops: list[RelationshipDrop] = []
    for key in sorted(seen):
        candidates = seen[key]
        if len(candidates) == 1 or all(candidate == candidates[0] for candidate in candidates[1:]):
            links.append(candidates[0])
            continue
        evidence = candidates[0].mapping_evidence
        drops.append(
            RelationshipDrop(
                reason=RelationshipDropReason.CONFLICTING_DUPLICATE,
                mapping_id=evidence.mapping_id if evidence is not None else None,
                source_property_path=(
                    evidence.source_property_path if evidence is not None else None
                ),
            )
        )
    return tuple(links), tuple(drops)


def _reconcile_unmapped_resources(
    result: ResourceQueryResult,
    coverage: ProviderScopeCoverage,
) -> tuple[InventoryBatch, ProviderScopeCoverage]:
    """Require every unmapped provider row exactly once before final-fence promotion."""
    resources = _dedupe_resources(result.resources)
    provider_counts: Counter[str] = Counter()
    for resource in resources:
        if resource.type != UNCLASSIFIED_RESOURCE_TYPE:
            raise RuntimeError("unmapped provider query returned a classified resource")
        provider_type = resource.props.get("providerType")
        if not isinstance(provider_type, str) or not provider_type.strip():
            raise RuntimeError("unclassified resource lacks its provider type")
        provider_counts[provider_type.strip().lower()] += 1
    expected_counts = Counter(
        {item.provider_type: item.count for item in coverage.unmapped_provider_types}
    )
    if provider_counts != expected_counts:
        raise RuntimeError(
            "unclassified resource identities do not reconcile with provider coverage"
        )
    links, duplicate_drops = _validate_links(result.links)
    return (
        InventoryBatch(
            resources=resources,
            links=links,
            relationship_drops=(*result.relationship_drops, *duplicate_drops),
        ),
        replace(
            coverage,
            materialized_unmapped_provider_object_count=len(resources),
        ),
    )


__all__ = [
    "ActivityLogFetchFn",
    "ActivityLogPage",
    "AzureInventoryConfig",
    "AzureResourceGraphInventory",
    "ResourceQueryFn",
    "ResourceQueryResult",
    "UnmappedResourceQueryFn",
]
