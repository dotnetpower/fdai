"""Fail-closed full-snapshot coordinator with ordered source fallback."""

from __future__ import annotations

import asyncio
import logging
import math
import socket
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol, cast

import httpx
from fdai_service_contracts.recorded_resource_state import (
    RECORDED_STATE_UNAVAILABLE_REASONS,
    STATE_FACT_UNAVAILABLE_REASONS_PROPERTY,
)

from fdai.delivery.inventory_relationship_verifier import verify_inventory_relationships
from fdai.delivery.inventory_sync_models import (
    InventoryProjectionSourceState as InventoryProjectionSourceState,
)
from fdai.delivery.inventory_sync_models import (
    InventoryProjectionSourceStatus as InventoryProjectionSourceStatus,
)
from fdai.delivery.inventory_sync_models import (
    InventoryRelationshipCoverage as InventoryRelationshipCoverage,
)
from fdai.delivery.inventory_sync_models import (
    PromotedInventoryObservation as PromotedInventoryObservation,
)
from fdai.delivery.inventory_sync_models import (
    compute_relationship_coverage as compute_relationship_coverage,
)
from fdai.delivery.kubernetes_relationships import project_kubernetes_relationships
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    ProviderRelationshipMappingCatalog,
)
from fdai.shared.providers.inventory import (
    Inventory,
    InventoryBatch,
    LinkRecord,
    ProviderScopeCoverage,
    RelationshipDrop,
    ResourceRecord,
)
from fdai.shared.providers.inventory_snapshot import (
    InventoryAttemptFailure,
    InventoryCoverageManifest,
    InventoryFailureCode,
    InventorySnapshotStore,
    InventorySource,
    InventorySourcesExhaustedError,
    InventorySyncResult,
)
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.state_evidence import (
    STATE_FACT_EQUAL_TIME_CONFLICT,
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

_LOG = logging.getLogger(__name__)

#: Accumulation ceilings for the optional observation handed to a derived read
#: model. They mirror the projection builder bounds so an oversized stream
#: degrades to an explicitly incomplete observation instead of exhausting memory.
_MAX_OBSERVED_RESOURCES = 50_000
_MAX_OBSERVED_LINKS = 200_000
_MAX_OBSERVED_DROPS = 200_000
INVENTORY_ACTIVE_SCOPE_CHECKPOINT_KEY = "inventory-ontology:active-scope-checkpoint"
DEFAULT_PROGRESS_DEADLINE_SECONDS = 900.0
DEFAULT_ATTEMPT_DEADLINE_SECONDS = 1500.0
MAX_ATTEMPT_DEADLINE_SECONDS = 1740.0
_RUN_LOCK_ID = "inventory-sync-coordinator"


#: Receives one promoted observation after the active pointer moves. The sink
#: owns a derived read model only; it never gains promotion authority.
InventoryPromotionObserver = Callable[[PromotedInventoryObservation], Awaitable[None]]
InventoryPromotionRecovery = Callable[[], Awaitable[None]]


class InventoryPromotionEnricher(Protocol):
    """Add verified read-plane links before the inventory single writer promotes them."""

    async def enrich(
        self,
        observation: PromotedInventoryObservation,
    ) -> PromotedInventoryObservation: ...


class InventoryStreamError(RuntimeError):
    """An inventory stream violated its atomic-fence contract."""


class InventoryPromotionObserverError(RuntimeError):
    """The authoritative snapshot advanced but its derived projection failed."""


class InventorySyncCoordinator:
    """Stage one source at a time and promote only a complete stream."""

    def __init__(
        self,
        *,
        store: InventorySnapshotStore,
        promotion_observer: InventoryPromotionObserver | None = None,
        promotion_enricher: InventoryPromotionEnricher | None = None,
        pre_run_recovery: InventoryPromotionRecovery | None = None,
        run_lock: ResourceLock | None = None,
        relationship_mapping_catalog: ProviderRelationshipMappingCatalog | None = None,
        progress_deadline_seconds: float = DEFAULT_PROGRESS_DEADLINE_SECONDS,
        attempt_deadline_seconds: float = DEFAULT_ATTEMPT_DEADLINE_SECONDS,
    ) -> None:
        if not math.isfinite(progress_deadline_seconds) or progress_deadline_seconds <= 0:
            raise ValueError("inventory progress_deadline_seconds MUST be > 0")
        if (
            not math.isfinite(attempt_deadline_seconds)
            or attempt_deadline_seconds < progress_deadline_seconds
        ):
            raise ValueError(
                "inventory attempt_deadline_seconds MUST be >= progress_deadline_seconds"
            )
        if attempt_deadline_seconds > MAX_ATTEMPT_DEADLINE_SECONDS:
            raise ValueError(
                "inventory attempt_deadline_seconds MUST resolve before the abandonment window"
            )
        self._store = store
        self._observer = promotion_observer
        self._enricher = promotion_enricher
        self._pre_run_recovery = pre_run_recovery
        self._run_lock = run_lock
        self._relationship_mapping_catalog = relationship_mapping_catalog
        self._progress_deadline_seconds = progress_deadline_seconds
        self._attempt_deadline_seconds = attempt_deadline_seconds

    async def run(self, sources: Sequence[InventorySource]) -> InventorySyncResult:
        if not sources:
            raise ValueError("sources MUST NOT be empty")
        try:
            async with asyncio.timeout(self._attempt_deadline_seconds):
                if self._run_lock is None:
                    return await self._run_locked(sources)
                async with self._run_lock.acquire(_RUN_LOCK_ID):
                    return await self._run_locked(sources)
        except TimeoutError as exc:
            raise InventorySourcesExhaustedError(
                (
                    InventoryAttemptFailure(
                        code=InventoryFailureCode.PARTIAL,
                        message="inventory run exceeded its end-to-end deadline",
                    ),
                )
            ) from exc

    async def _run_locked(self, sources: Sequence[InventorySource]) -> InventorySyncResult:
        if self._pre_run_recovery is not None:
            try:
                await self._pre_run_recovery()
            except Exception as exc:
                raise InventoryPromotionObserverError(
                    "pending inventory projection recovery failed"
                ) from exc
        failures: list[InventoryAttemptFailure] = []
        for source in sources:
            attempt_id = await self._store.begin(source.manifest)
            observed = _ObservationAccumulator(
                enabled=self._observer is not None or self._enricher is not None,
                relationship_mapping_catalog=self._relationship_mapping_catalog,
            )
            try:
                completed, provider_scope_coverage = await self._stage_stream(
                    attempt_id,
                    cast(Inventory, source.inventory).full_snapshot(),
                    observed,
                )
                promoted_observation = observed.result(
                    generation=attempt_id,
                    recorded_at=datetime.now(tz=UTC),
                )
                if not promoted_observation.complete:
                    raise InventoryStreamError(
                        "inventory observation exceeded its projection bounds"
                    )
                if source.manifest.metadata.get("coverage_scope") == "requested_resource_types":
                    raise InventoryStreamError(
                        "resource-type subset cannot promote the global inventory snapshot"
                    )
                if self._enricher is not None:
                    original_drop_count = len(promoted_observation.relationship_drops)
                    enriched = await self._enricher.enrich(promoted_observation)
                    changed_resources, added_links = _validate_enrichment(
                        promoted_observation,
                        enriched,
                    )
                    if changed_resources or added_links:
                        await self._store.stage(
                            attempt_id,
                            InventoryBatch(
                                resources=changed_resources,
                                links=added_links,
                            ),
                        )
                    promoted_observation = enriched
                    observed.add_relationship_drops(
                        enriched.relationship_drops[original_drop_count:]
                    )
                    if enriched.recorded_at is not None and enriched.recorded_at > completed:
                        completed = enriched.recorded_at
                metadata = dict(source.manifest.metadata)
                metadata.pop("provider_scope_coverage", None)
                relationship_drop_reasons = observed.relationship_drop_reasons(
                    promoted_observation.relationship_drops
                )
                metadata["relationship_complete"] = not relationship_drop_reasons
                metadata["relationship_drop_reasons"] = list(relationship_drop_reasons)
                metadata["relationship_drop_classifications"] = list(
                    observed.relationship_drop_classifications(
                        promoted_observation.relationship_drops
                    )
                )
                metadata["derived_source_states"] = [
                    state.to_metadata()
                    for state in promoted_observation.source_states
                    if not state.additive
                ]
                additive_source_states = [
                    state.to_metadata()
                    for state in promoted_observation.source_states
                    if state.additive
                ]
                if additive_source_states:
                    metadata["additive_source_states"] = additive_source_states
                if promoted_observation.state_base_generation_checked:
                    metadata["state_base_generation"] = promoted_observation.state_base_generation
                metadata["projection_complete"] = promoted_observation.complete
                metadata["relationship_coverage"] = compute_relationship_coverage(
                    promoted_observation
                ).to_metadata()
                if provider_scope_coverage is not None:
                    metadata["provider_scope_coverage"] = provider_scope_coverage.to_metadata()
                manifest = InventoryCoverageManifest(
                    source=source.manifest.source,
                    scopes=source.manifest.scopes,
                    resource_types=source.manifest.resource_types,
                    observation_kind=source.manifest.observation_kind,
                    started_at=source.manifest.started_at,
                    completed_at=completed,
                    metadata=metadata,
                )
                await self._store.promote(attempt_id, manifest)
            except asyncio.CancelledError:
                try:
                    async with asyncio.timeout(5):
                        await self._store.fail(
                            attempt_id,
                            InventoryAttemptFailure(
                                code=InventoryFailureCode.PARTIAL,
                                message=(
                                    "inventory candidate was cancelled before promotion completed"
                                ),
                            ),
                        )
                except Exception as cleanup_error:
                    _LOG.warning(
                        "inventory_cancel_cleanup_failed",
                        extra={"error_type": type(cleanup_error).__name__},
                    )
                raise
            except Exception as exc:  # noqa: BLE001 - source boundary, classified and retained
                failure = classify_inventory_failure(exc)
                await self._store.fail(attempt_id, failure)
                failures.append(failure)
                continue
            await self._notify_promotion(promoted_observation)
            return InventorySyncResult(
                attempt_id=attempt_id,
                source=source.name,
                failures=tuple(failures),
            )
        raise InventorySourcesExhaustedError(failures)

    async def _notify_promotion(self, observation: PromotedInventoryObservation) -> None:
        """Hand the promoted observation to the derived read model.

        The promoted snapshot is already authoritative, so a failing derived
        projection is recorded and left behind rather than invalidating it.
        """
        if self._observer is None:
            return
        try:
            await self._observer(observation)
        except Exception as exc:
            _LOG.exception(
                "inventory_promotion_observer_failed",
                extra={"generation": observation.generation},
            )
            raise InventoryPromotionObserverError(
                "inventory promotion observer failed after authoritative promotion"
            ) from exc

    async def _stage_stream(
        self,
        attempt_id: str,
        stream: AsyncIterator[InventoryBatch],
        observed: _ObservationAccumulator,
    ) -> tuple[datetime, ProviderScopeCoverage | None]:
        """Stage one source under a re-arming progress deadline and hard ceiling."""

        saw_final = False
        provider_scope_coverage: ProviderScopeCoverage | None = None
        loop = asyncio.get_running_loop()
        ceiling_at = loop.time() + self._attempt_deadline_seconds

        def _next_deadline() -> float:
            return min(ceiling_at, loop.time() + self._progress_deadline_seconds)

        try:
            async with asyncio.timeout(self._attempt_deadline_seconds) as deadline:
                deadline.reschedule(_next_deadline())
                async for batch in stream:
                    deadline.reschedule(_next_deadline())
                    if saw_final:
                        raise InventoryStreamError(
                            "inventory stream emitted data after final fence"
                        )
                    if batch.final:
                        saw_final = True
                        provider_scope_coverage = batch.provider_scope_coverage
                    if batch.resources or batch.links or batch.relationship_drops:
                        observed.add(batch)
                    if batch.resources or batch.links:
                        await self._store.stage(
                            attempt_id,
                            InventoryBatch(
                                resources=batch.resources,
                                links=batch.links,
                                cursor=batch.cursor,
                            ),
                        )
        except TimeoutError as exc:
            reason = "absolute ceiling" if loop.time() >= ceiling_at else "no-progress deadline"
            raise InventoryStreamError(f"inventory source exceeded its {reason}") from exc
        finally:
            aclose = getattr(stream, "aclose", None)
            if callable(aclose):
                await aclose()
        if not saw_final:
            raise InventoryStreamError("inventory stream ended before final fence")
        return datetime.now(tz=UTC), provider_scope_coverage


class _ObservationAccumulator:
    """Collect streamed records for the optional derived projection only."""

    def __init__(
        self,
        *,
        enabled: bool,
        relationship_mapping_catalog: ProviderRelationshipMappingCatalog | None,
    ) -> None:
        self._enabled = enabled
        self._relationship_mapping_catalog = relationship_mapping_catalog
        self._resources: list[ResourceRecord] = []
        self._links: list[LinkRecord] = []
        self._relationship_drops: list[RelationshipDrop] = []
        self._truncated = False

    def add(self, batch: InventoryBatch) -> None:
        if len(self._relationship_drops) + len(batch.relationship_drops) > _MAX_OBSERVED_DROPS:
            raise InventoryStreamError("inventory relationship drops exceeded their bound")
        self._relationship_drops.extend(batch.relationship_drops)
        if not self._enabled or self._truncated:
            return
        if (
            len(self._resources) + len(batch.resources) > _MAX_OBSERVED_RESOURCES
            or len(self._links) + len(batch.links) > _MAX_OBSERVED_LINKS
        ):
            self._truncated = True
            self._resources.clear()
            self._links.clear()
            return
        self._resources.extend(batch.resources)
        self._links.extend(batch.links)

    def relationship_drop_reasons(
        self, drops: Sequence[RelationshipDrop] | None = None
    ) -> tuple[str, ...]:
        """Return stable relationship coverage gaps for the promoted snapshot manifest."""

        selected = self._relationship_drops if drops is None else drops
        reasons = {drop.reason.value for drop in selected}
        if self._truncated:
            reasons.add("partial_generation")
        return tuple(sorted(reasons))

    def add_relationship_drops(self, drops: Sequence[RelationshipDrop]) -> None:
        """Include enrichment gaps in the promotion coverage metadata."""

        if len(self._relationship_drops) + len(drops) > _MAX_OBSERVED_DROPS:
            raise InventoryStreamError("inventory relationship drops exceeded their bound")
        self._relationship_drops.extend(drops)

    def relationship_drop_classifications(
        self, drops: Sequence[RelationshipDrop] | None = None
    ) -> tuple[dict[str, object], ...]:
        """Return bounded mapping-specific counts without provider identifiers."""

        classified = self._relationship_drops if drops is None else drops
        counts = Counter(
            (
                drop.reason.value,
                drop.mapping_id or "unattributed",
                drop.source_property_path or "unattributed",
                drop.source_provider_type or "unattributed",
                drop.target_provider_type or "unresolved",
                (
                    drop.unavailable_reason.value
                    if drop.unavailable_reason is not None
                    else "unclassified"
                ),
            )
            for drop in classified
        )
        if self._truncated:
            counts[
                (
                    "partial_generation",
                    "unattributed",
                    "unattributed",
                    "unattributed",
                    "unresolved",
                    "unclassified",
                )
            ] += 1
        return tuple(
            {
                "reason": reason,
                "mapping_id": mapping_id,
                "source_property_path": source_property_path,
                "source_provider_type": source_provider_type,
                "target_provider_type": target_provider_type,
                "unavailable_reason": unavailable_reason,
                "count": count,
            }
            for (
                reason,
                mapping_id,
                source_property_path,
                source_provider_type,
                target_provider_type,
                unavailable_reason,
            ), count in sorted(counts.items())
        )

    def result(self, *, generation: str, recorded_at: datetime) -> PromotedInventoryObservation:
        projected = (
            project_kubernetes_relationships(
                self._resources,
                catalog=self._relationship_mapping_catalog,
                complete=not self._truncated,
            )
            if self._relationship_mapping_catalog is not None
            else None
        )
        verified = verify_inventory_relationships(
            generation=generation,
            mapping_catalog=self._relationship_mapping_catalog,
            resources=self._resources,
            links=((*self._links, *projected.links) if projected is not None else self._links),
            complete=not self._truncated,
            recorded_at=recorded_at,
            upstream_drops=(
                (*self._relationship_drops, *projected.dropped)
                if projected is not None
                else self._relationship_drops
            ),
        )
        return PromotedInventoryObservation(
            generation=generation,
            resources=tuple(self._resources),
            links=verified.links,
            complete=not self._truncated,
            relationship_drops=verified.dropped,
            recorded_at=recorded_at,
        )


def classify_inventory_failure(exc: Exception) -> InventoryAttemptFailure:
    """Map transport and contract failures to a bounded, secret-free code."""

    message = type(exc).__name__
    code = InventoryFailureCode.SOURCE_UNAVAILABLE
    internal_reason = _internal_inventory_failure_reason(exc)
    if internal_reason is not None:
        return InventoryAttemptFailure(
            code=InventoryFailureCode.INVALID_DATA,
            message=internal_reason,
        )
    if isinstance(exc, InventoryStreamError):
        code = InventoryFailureCode.PARTIAL
        message = str(exc)
    elif isinstance(exc, (httpx.ConnectTimeout, httpx.ConnectError)):
        cause = exc.__cause__
        code = (
            InventoryFailureCode.DNS_FAILED
            if isinstance(cause, socket.gaierror)
            else InventoryFailureCode.NETWORK_BLOCKED
        )
    else:
        text = str(exc).lower()
        if "http 401" in text or "identity token request failed" in text:
            code = InventoryFailureCode.TOKEN_FAILED
        elif "http 403" in text or "forbidden" in text:
            code = InventoryFailureCode.FORBIDDEN
        elif "http 429" in text or "throttl" in text:
            code = InventoryFailureCode.THROTTLED
        elif any(
            reason in text for reason in ("pagination cap", "partial", "truncated", "continuation")
        ):
            code = InventoryFailureCode.PARTIAL
        elif isinstance(exc, (ValueError, TypeError)):
            code = InventoryFailureCode.INVALID_DATA
    return InventoryAttemptFailure(code=code, message=message[:200])


def _internal_inventory_failure_reason(exc: Exception) -> str | None:
    """Classify reviewed invariant failures without retaining target identifiers."""
    text = str(exc)
    exact = {
        "inventory candidate contains a link with a missing endpoint": (
            "dangling_relationship_endpoint"
        ),
        "inventory candidate violates contains parent cardinality": (
            "ambiguous_containment_parent"
        ),
    }
    if reason := exact.get(text):
        return reason
    if (
        isinstance(exc, RuntimeError)
        and text.startswith("inventory resource ")
        and text.endswith(" has conflicting duplicates")
    ):
        return "conflicting_resource_duplicate"
    return None


def _validate_enrichment(
    original: PromotedInventoryObservation,
    enriched: PromotedInventoryObservation,
) -> tuple[tuple[ResourceRecord, ...], tuple[LinkRecord, ...]]:
    """Require enrichment to preserve the promoted provider observation exactly."""

    if (
        enriched.generation != original.generation
        or enriched.complete != original.complete
        or enriched.recorded_at is None
        or original.recorded_at is None
        or enriched.recorded_at < original.recorded_at
        or (
            original.state_base_generation is not None
            and enriched.state_base_generation != original.state_base_generation
        )
        or (original.state_base_generation_checked and not enriched.state_base_generation_checked)
    ):
        raise ValueError("inventory enrichment MUST preserve the provider observation")
    if enriched.state_base_generation is not None and not enriched.state_base_generation_checked:
        raise ValueError("inventory state base generation requires an explicit check")
    if enriched.state_base_generation is not None and (
        not enriched.state_base_generation.strip() or len(enriched.state_base_generation) > 256
    ):
        raise ValueError("inventory state base generation MUST be bounded")
    original_drops = tuple(original.relationship_drops)
    enriched_drops = tuple(enriched.relationship_drops)
    if enriched_drops[: len(original_drops)] != original_drops:
        raise ValueError("inventory enrichment MUST preserve existing relationship drops")
    original_resources = {resource.resource_id: resource for resource in original.resources}
    enriched_resources = {resource.resource_id: resource for resource in enriched.resources}
    if len(enriched_resources) != len(enriched.resources):
        raise ValueError("inventory enrichment resources MUST have unique identities")
    changed_resources: list[ResourceRecord] = []
    for key, resource in original_resources.items():
        candidate = enriched_resources.get(key)
        if candidate is None:
            raise ValueError("inventory enrichment MUST preserve provider resources")
        if candidate != resource:
            _validate_resource_state_enrichment(resource, candidate)
            changed_resources.append(candidate)
    changed_resources.extend(
        resource for key, resource in enriched_resources.items() if key not in original_resources
    )
    original_by_key = {(link.from_id, link.link_type, link.to_id): link for link in original.links}
    enriched_by_key = {(link.from_id, link.link_type, link.to_id): link for link in enriched.links}
    if len(enriched_by_key) != len(enriched.links):
        raise ValueError("inventory enrichment links MUST have unique identities")
    if any(enriched_by_key.get(key) != link for key, link in original_by_key.items()):
        raise ValueError("inventory enrichment MUST NOT replace provider links")
    added = tuple(link for key, link in enriched_by_key.items() if key not in original_by_key)
    resource_types = {resource.resource_id: resource.type for resource in enriched.resources}
    if any(
        resource_types.get(link.from_id) != link.from_type
        or resource_types.get(link.to_id) != link.to_type
        for link in added
    ):
        raise ValueError("inventory enrichment links MUST match promoted resource endpoints")
    if any(
        link.observation_metadata is None or not link.observation_metadata.verified
        for link in added
    ):
        raise ValueError("inventory enrichment MUST add only verified links")
    if len({(state.source, state.scope_digest) for state in enriched.source_states}) != len(
        enriched.source_states
    ):
        raise ValueError("inventory enrichment source states MUST be unique")
    return (
        tuple(sorted(changed_resources, key=lambda resource: resource.resource_id)),
        tuple(sorted(added, key=lambda link: (link.from_id, link.link_type, link.to_id))),
    )


def _validate_resource_state_enrichment(
    original: ResourceRecord,
    enriched: ResourceRecord,
) -> None:
    """Allow only reviewed provider-observed state facts on an existing Resource."""

    if (
        enriched.resource_id != original.resource_id
        or enriched.type != original.type
        or enriched.provider_ref != original.provider_ref
        or enriched.last_seen != original.last_seen
    ):
        raise ValueError("inventory state enrichment MUST preserve Resource identity")
    original_props = dict(original.props)
    enriched_props = dict(enriched.props)
    for key, value in original_props.items():
        if key == STATE_FACT_METADATA_PROPERTY:
            continue
        if enriched_props.get(key) != value:
            raise ValueError("inventory state enrichment MUST preserve provider properties")
    allowed = {
        "availabilityState",
        "availabilityReasonKind",
        STATE_FACT_METADATA_PROPERTY,
        STATE_FACT_UNAVAILABLE_REASONS_PROPERTY,
    }
    if original.type == "llm-model-deployment":
        allowed.add("servingState")
    if original.type == "static-web-app":
        allowed.add("staticSiteEnvironmentStatus")
    if set(enriched_props) - set(original_props) - allowed:
        raise ValueError("inventory state enrichment added an unsupported property")
    unavailable_reasons = enriched_props.get(STATE_FACT_UNAVAILABLE_REASONS_PROPERTY)
    allowed_unavailable_keys = {"availabilityState"}
    if original.type == "llm-model-deployment":
        allowed_unavailable_keys.add("servingState")
    if unavailable_reasons is not None:
        if (
            not isinstance(unavailable_reasons, Mapping)
            or not set(unavailable_reasons)
            or set(unavailable_reasons) - allowed_unavailable_keys
            or any(
                reason not in RECORDED_STATE_UNAVAILABLE_REASONS
                or (key == "availabilityState" and not str(reason).startswith("resource_health_"))
                or (key == "servingState" and not str(reason).startswith("model_serving_"))
                for key, reason in unavailable_reasons.items()
            )
        ):
            raise ValueError("inventory state enrichment added an unsupported unavailable reason")
    if (
        "availabilityReasonKind" in enriched_props
        and "availabilityReasonKind" not in original_props
        and "availabilityState" not in enriched_props
    ):
        raise ValueError("inventory availability reason requires availability state")
    metadata = enriched_props.get(STATE_FACT_METADATA_PROPERTY)
    state_fact_keys = {
        key
        for key in ("availabilityState", "servingState", "staticSiteEnvironmentStatus")
        if key in enriched_props
    }
    if metadata is None and not state_fact_keys:
        metadata = {}
    elif not isinstance(metadata, Mapping):
        raise ValueError("inventory state enrichment MUST supply keyed state metadata")
    original_metadata = original_props.get(STATE_FACT_METADATA_PROPERTY)
    if original_metadata is not None:
        if not isinstance(original_metadata, Mapping):
            raise ValueError("inventory provider state metadata is malformed")
        if any(metadata.get(key) != value for key, value in original_metadata.items()):
            raise ValueError("inventory state enrichment MUST preserve existing state metadata")
    original_metadata_keys = (
        set(original_metadata) if isinstance(original_metadata, Mapping) else set()
    )
    allowed_metadata_keys = original_metadata_keys | state_fact_keys
    if set(metadata) - allowed_metadata_keys:
        raise ValueError("inventory state enrichment added unsupported state metadata")
    if "availabilityState" in enriched_props:
        _validate_observed_state_fact(
            state=enriched_props["availabilityState"],
            metadata=metadata.get("availabilityState"),
            authority=StateFactAuthority.PROVIDER,
            source_identity="azure-resource-health",
            source_revision_prefix="azure-resource-health:sha256:",
            allowed_states={"Available", "Degraded", "Unavailable", "Unknown"},
        )
    if "staticSiteEnvironmentStatus" in enriched_props:
        if original.type != "static-web-app":
            raise ValueError("Static Web App state enrichment requires a Static Web App Resource")
        _validate_observed_state_fact(
            state=enriched_props["staticSiteEnvironmentStatus"],
            metadata=metadata.get("staticSiteEnvironmentStatus"),
            authority=StateFactAuthority.PROVIDER,
            source_identity="azure-static-web-app-default-environment",
            source_revision_prefix="azure-static-web-app-environment:sha256:",
            allowed_states={
                "WaitingForDeployment",
                "Uploading",
                "Deploying",
                "Ready",
                "Failed",
                "Deleting",
                "Detached",
            },
        )
    if "servingState" in enriched_props:
        if original.type != "llm-model-deployment":
            raise ValueError("model serving enrichment requires a model deployment Resource")
        _validate_observed_state_fact(
            state=enriched_props["servingState"],
            metadata=metadata.get("servingState"),
            authority=StateFactAuthority.TELEMETRY,
            source_identity="azure-monitor-model-serving",
            source_revision_prefix="azure-monitor-model-serving:sha256:",
            allowed_states={"Serving"},
        )
    reviewed_state_keys = ("availabilityState", "servingState", "staticSiteEnvironmentStatus")
    if (
        not any(key in enriched_props for key in reviewed_state_keys)
        and unavailable_reasons is None
    ):
        raise ValueError(
            "inventory state enrichment MUST supply one reviewed state fact or unavailable reason"
        )


def _validate_observed_state_fact(
    *,
    state: object,
    metadata: object,
    authority: StateFactAuthority,
    source_identity: str,
    source_revision_prefix: str,
    allowed_states: set[str],
) -> None:
    if not isinstance(state, str) or not state.strip():
        raise ValueError("inventory state enrichment MUST supply a bounded state")
    if state not in allowed_states:
        raise ValueError("inventory state enrichment supplied an unsupported state")
    if not isinstance(metadata, Mapping):
        raise ValueError("inventory state metadata is missing")
    fact = StateFactMetadata.from_mapping(metadata)
    evidence_shape_valid = (fact.completeness == 1.0 and not fact.conflicts) or (
        fact.completeness == 0.0 and fact.conflicts == (STATE_FACT_EQUAL_TIME_CONFLICT,)
    )
    if (
        fact.lane is not StateFactLane.OBSERVED
        or fact.authority is not authority
        or fact.source_identity != source_identity
        or not _content_addressed_revision(fact.source_revision, source_revision_prefix)
        or fact.evidence_refs != (fact.source_revision,)
        or fact.synthetic
        or not evidence_shape_valid
    ):
        raise ValueError("inventory state metadata is not authoritative observed evidence")


def _content_addressed_revision(value: str, prefix: str) -> bool:
    digest = value.removeprefix(prefix)
    return (
        value.startswith(prefix)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


__all__ = [
    "InventoryProjectionSourceState",
    "InventoryProjectionSourceStatus",
    "InventoryPromotionObserverError",
    "InventoryRelationshipCoverage",
    "InventoryStreamError",
    "InventoryPromotionEnricher",
    "InventoryPromotionObserver",
    "InventoryPromotionRecovery",
    "InventorySyncCoordinator",
    "classify_inventory_failure",
    "compute_relationship_coverage",
]
