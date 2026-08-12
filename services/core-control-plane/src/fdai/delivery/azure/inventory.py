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
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Final

from fdai.shared.providers.inventory import (
    InventoryBatch,
    LinkRecord,
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
        delta_fetch: ActivityLogFetchFn | None = None,
    ) -> None:
        if config.max_concurrent_queries < 1:
            raise ValueError("AzureInventoryConfig.max_concurrent_queries MUST be >= 1")
        if config.max_delta_pages < 1:
            raise ValueError("AzureInventoryConfig.max_delta_pages MUST be >= 1")
        self._config = config
        self._query = query
        self._delta_fetch = delta_fetch

    # ------------------------------------------------------------------
    # Inventory Protocol
    # ------------------------------------------------------------------

    async def full_snapshot(self, since: str | None = None) -> AsyncIterator[InventoryBatch]:
        """Parallel full-scan, sharded by ``resource_type``.

        Emits one :class:`InventoryBatch` per shard as its ARG query
        completes, then a final ``final=True`` fence batch the caller
        uses to atomically promote the new graph
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

        try:
            for coro in asyncio.as_completed(tasks):
                batch = await coro
                if batch.resources or batch.links or batch.relationship_drops:
                    yield batch
        except BaseException:
            # Fail-closed: cancel outstanding shards so a partial snapshot
            # never quietly lands. The caller retains the previous graph
            # because we never yielded a `final=True` batch. Await the
            # cancels so shard sockets close before the exception unwinds
            # past our generator - otherwise aiohttp / httpx warn about
            # unfinished coroutines on shutdown.
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        yield InventoryBatch(final=True)

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
        seen[record.resource_id] = record
    return tuple(seen.values())


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
        if len(candidates) == 1:
            links.append(candidates[0])
            continue
        reason = (
            RelationshipDropReason.DUPLICATE_EDGE
            if all(candidate == candidates[0] for candidate in candidates[1:])
            else RelationshipDropReason.CONFLICTING_DUPLICATE
        )
        evidence = candidates[0].mapping_evidence
        drops.append(
            RelationshipDrop(
                reason=reason,
                mapping_id=evidence.mapping_id if evidence is not None else None,
                source_property_path=(
                    evidence.source_property_path if evidence is not None else None
                ),
            )
        )
    return tuple(links), tuple(drops)


__all__ = [
    "ActivityLogFetchFn",
    "ActivityLogPage",
    "AzureInventoryConfig",
    "AzureResourceGraphInventory",
    "ResourceQueryFn",
    "ResourceQueryResult",
]
