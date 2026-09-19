"""Collect a bounded Azure inventory through injected authenticated provider reads.

``AzureArgQueryFactory`` supplies reviewed queries and identity-bound HTTP transport.
Full scans combine resource-type shards, reconcile provider coverage, close relationship
endpoints, and redact environment bindings before returning one complete generation.
Empty progress batches carry no evidence. Any failed shard or coverage mismatch omits
the final fence, so the coordinator retains its previous authoritative snapshot.

Resource duplicates with equal content retain their earliest observation time; content
conflicts fail the generation. Activity Log delta pagination uses the same final-fence
contract, while unbound deltas return no observations. Only the inventory coordinator
and its owned projection persist observations; this adapter never writes ontology state.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Final

from fdai.delivery.azure.inventory_redaction import redact_runtime_environment
from fdai.shared.providers.inventory import (
    UNCLASSIFIED_RESOURCE_TYPE,
    InventoryBatch,
    LinkRecord,
    ProviderScopeCoverage,
    RelationshipDrop,
    RelationshipDropReason,
    RelationshipUnavailableReason,
    ResourceRecord,
)

_DEFAULT_MAX_CONCURRENT_QUERIES: Final[int] = 4
_DEFAULT_MAX_DELTA_PAGES: Final[int] = 64
InventoryShardObserver = Callable[[int, int, int, int], Awaitable[object]]
InventorySourceObserver = Callable[[], Awaitable[object]]


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
GenerationRelationshipFn = Callable[[Sequence[ResourceRecord]], ResourceQueryResult]


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
    path is live once bound; the delta path uses an independently supplied
    Activity Log fetch function and never manufactures observations when unbound.
    """

    def __init__(
        self,
        *,
        config: AzureInventoryConfig,
        query: ResourceQueryFn,
        scope_coverage: ScopeCoverageFn | None = None,
        unmapped_resources: UnmappedResourceQueryFn | None = None,
        generation_relationships: GenerationRelationshipFn | None = None,
        delta_fetch: ActivityLogFetchFn | None = None,
        shard_observer: InventoryShardObserver | None = None,
        source_observer: InventorySourceObserver | None = None,
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
        self._generation_relationships = generation_relationships
        self._delta_fetch = delta_fetch
        self._shard_observer = shard_observer
        self._source_observer = source_observer

    # ------------------------------------------------------------------
    # Inventory Protocol
    # ------------------------------------------------------------------

    async def full_snapshot(self, since: str | None = None) -> AsyncIterator[InventoryBatch]:
        """Parallel full-scan, sharded by ``resource_type``.

        Validates and combines all completed shards into one generation
        :class:`InventoryBatch`, then emits a final ``final=True`` fence
        batch the caller uses to atomically promote the new graph
        (``docs/roadmap/architecture/csp-neutrality.md § 5``).

        ``since`` is currently unused - reconciliation returns the full shard
        each call. Production may honor it as an ``since <= last_seen``
        optimization; it MUST NOT substitute for :meth:`delta`.
        """
        del since  # reserved (see docstring)

        if self._source_observer is not None:
            await self._source_observer()

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
                batch = await coro
                completed.append(batch)
                if self._shard_observer is not None:
                    await self._shard_observer(
                        len(batch.resources),
                        len(batch.links),
                        0,
                        len(batch.relationship_drops),
                    )
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
                if self._shard_observer is not None:
                    await self._shard_observer(
                        len(unmapped_batch.resources),
                        len(unmapped_batch.links),
                        len(unmapped_batch.resources),
                        len(unmapped_batch.relationship_drops),
                    )
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
        if provider_scope_coverage is not None:
            expected_types = provider_scope_coverage.mapped_provider_types
            if expected_types is None:
                matched = (
                    sum(
                        resource.type
                        not in {UNCLASSIFIED_RESOURCE_TYPE, "subscription", "network.subnet"}
                        for resource in resources
                    )
                    == provider_scope_coverage.mapped_provider_object_count
                )
            else:
                expected = Counter(
                    {item.provider_type.casefold(): item.count for item in expected_types}
                )
                observed = Counter(
                    provider_type.casefold()
                    for resource in resources
                    if resource.type != UNCLASSIFIED_RESOURCE_TYPE
                    and isinstance(provider_type := resource.props.get("providerType"), str)
                    and provider_type.casefold() in expected
                )
                matched = (
                    sum(expected.values()) == provider_scope_coverage.mapped_provider_object_count
                    and observed == expected
                )
            if not matched:
                raise RuntimeError(
                    "mapped resource identities do not reconcile with provider coverage"
                )
        generation_relationships = (
            self._generation_relationships(resources)
            if self._generation_relationships is not None
            else ResourceQueryResult()
        )
        links, generation_drops = _validate_links(
            (
                *(link for batch in completed for link in batch.links),
                *generation_relationships.links,
            )
        )
        links, endpoint_drops = _close_generation_endpoints(resources, links)
        resources = tuple(redact_runtime_environment(resource) for resource in resources)
        relationship_drops = (
            tuple(drop for batch in completed for drop in batch.relationship_drops)
            + generation_relationships.relationship_drops
            + generation_drops
            + endpoint_drops
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

        With no fetch bound, this yields a single ``final=True`` empty batch so callers
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
            resources = tuple(
                redact_runtime_environment(resource)
                for resource in _dedupe_resources(page.resources)
            )
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
            if (
                existing.type != record.type
                or existing.props != record.props
                or existing.provider_ref != record.provider_ref
            ):
                raise RuntimeError(
                    f"inventory resource {record.resource_id!r} has conflicting duplicates"
                )
            if existing.last_seen is None or (
                record.last_seen is not None
                and datetime.fromisoformat(existing.last_seen.replace("Z", "+00:00"))
                <= datetime.fromisoformat(record.last_seen.replace("Z", "+00:00"))
            ):
                continue
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
                source_provider_type=(
                    evidence.source_provider_type if evidence is not None else None
                ),
                target_provider_type=(
                    evidence.target_provider_type if evidence is not None else None
                ),
            )
        )
    return tuple(links), tuple(drops)


def _close_generation_endpoints(
    resources: Sequence[ResourceRecord],
    links: Sequence[LinkRecord],
) -> tuple[tuple[LinkRecord, ...], tuple[RelationshipDrop, ...]]:
    """Keep only candidates whose exact typed endpoints exist in this complete generation."""

    resource_types = {resource.resource_id: resource.type for resource in resources}
    closed: list[LinkRecord] = []
    drops: list[RelationshipDrop] = []
    for link in links:
        source_type = resource_types.get(link.from_id)
        target_type = resource_types.get(link.to_id)
        reason: RelationshipDropReason | None = None
        if source_type is None:
            reason = RelationshipDropReason.MISSING_SOURCE_ENDPOINT
        elif target_type is None:
            reason = RelationshipDropReason.MISSING_TARGET_ENDPOINT
        elif (source_type, target_type) != (link.from_type, link.to_type):
            reason = RelationshipDropReason.TARGET_TYPE_MISMATCH
        if reason is None:
            closed.append(link)
            continue
        evidence = link.mapping_evidence
        unavailable_reason = None
        if reason is RelationshipDropReason.MISSING_SOURCE_ENDPOINT:
            unavailable_reason = RelationshipUnavailableReason.SOURCE_OUTSIDE_ACTIVE_GENERATION
        elif reason is RelationshipDropReason.MISSING_TARGET_ENDPOINT:
            unavailable_reason = RelationshipUnavailableReason.TARGET_OUTSIDE_ACTIVE_GENERATION
        elif reason is RelationshipDropReason.TARGET_TYPE_MISMATCH:
            unavailable_reason = RelationshipUnavailableReason.TARGET_PROVIDER_TYPE_UNMODELED
        drops.append(
            RelationshipDrop(
                reason=reason,
                mapping_id=evidence.mapping_id if evidence is not None else None,
                source_property_path=(
                    evidence.source_property_path if evidence is not None else None
                ),
                source_provider_type=(
                    evidence.source_provider_type if evidence is not None else None
                ),
                target_provider_type=(
                    evidence.target_provider_type if evidence is not None else None
                ),
                unavailable_reason=unavailable_reason,
            )
        )
    return tuple(closed), tuple(
        sorted(
            drops,
            key=lambda item: (
                item.reason.value,
                item.mapping_id or "",
                item.source_property_path or "",
                item.source_provider_type or "",
                item.target_provider_type or "",
            ),
        )
    )


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
    "GenerationRelationshipFn",
    "ResourceQueryFn",
    "ResourceQueryResult",
    "UnmappedResourceQueryFn",
]
