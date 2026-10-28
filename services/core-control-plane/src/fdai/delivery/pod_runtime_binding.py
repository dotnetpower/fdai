"""Production Pod binding using the Inventory Job's validated source contract."""

from __future__ import annotations

import asyncio
import os
import ssl
from collections.abc import Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from fdai.core.investigation.kubernetes_pod import (
    KubernetesPodLifecycleAnalyzer,
    PodLifecycleEvidence,
)
from fdai.core.investigation.kubernetes_pod_status import (
    KubernetesPodFailureAnalyzer,
    PodFailureEvidence,
    PodStatusEvidence,
)
from fdai.delivery.aks_subscription_discovery import StateStoreAksSubscriptionBindingCache
from fdai.delivery.azure.arg_projection import to_neutral_id
from fdai.delivery.inventory_job_config import InventoryJobConfig
from fdai.delivery.kubernetes_api_inventory import (
    KubernetesApiAuth,
    KubernetesApiInventoryConfig,
    KubernetesApiInventorySource,
    ServiceAccountTokenAuth,
    WorkloadIdentityKubernetesAuth,
)
from fdai.delivery.kubernetes_cluster_binding import KubernetesClusterBinding
from fdai.delivery.kubernetes_pod_evidence import LivePodLifecycleEvidenceSource
from fdai.delivery.kubernetes_pod_observations import PodEvidenceUnavailableError, text
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_kubernetes_lifecycle import (
    PostgresKubernetesLifecycleConfig,
    PostgresKubernetesLifecycleStore,
)
from fdai.delivery.persistence.postgres_promoted_inventory_reader import (
    PostgresPromotedInventoryGenerationReader,
)
from fdai.delivery.pod_evidence_binding import POD_EVIDENCE_ENV, build_pod_analyzer
from fdai.delivery.pod_recovery import PodRecoveryAnalyzer
from fdai.delivery.pod_tick_cache import PodTickCache, read_inventory
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    ProviderRelationshipMappingCatalog,
    load_provider_relationship_mapping_catalog,
)
from fdai.shared.providers.inventory import (
    PromotedInventoryGeneration,
    PromotedInventoryGenerationReader,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity


@dataclass(frozen=True)
class PodAnalyzerBinding:
    """An unavailable source is configuration evidence, never a healthy empty tick."""

    analyzer: KubernetesPodLifecycleAnalyzer | PodRecoveryAnalyzer | None
    unavailable_reason: str | None = None


async def build_production_pod_analyzer(
    *,
    stack: AsyncExitStack,
    identity: WorkloadIdentity | None = None,
    dsn: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> PodAnalyzerBinding:
    """Compose without Azure/Kubernetes/DB reads or token loading.

    ``stack`` owns created HTTP clients and the discovery-cache StateStore.
    The caller retains ownership of its existing workload identity. Explicit
    JSON replay wins before any production configuration is evaluated.
    """

    environment = dict(os.environ if environ is None else environ)
    if environment.get(POD_EVIDENCE_ENV, "").strip():
        replay = build_pod_analyzer(environment)
        if not isinstance(replay, KubernetesPodLifecycleAnalyzer):
            raise ValueError("Pod replay binding MUST produce a lifecycle analyzer")
        return PodAnalyzerBinding(replay)
    if not environment.get("FDAI_INVENTORY_DSN", "").strip() and dsn:
        environment["FDAI_INVENTORY_DSN"] = dsn
    if not environment.get("FDAI_INVENTORY_DSN", "").strip():
        return PodAnalyzerBinding(None, "inventory_dsn_unbound")
    try:
        config = InventoryJobConfig.from_env(environment)
        if config.kubernetes_connector_registration_path is not None:
            return PodAnalyzerBinding(None, "kubernetes_connector_status_source_unbound")
        if not config.kubernetes_bindings and not config.kubernetes_subscription_discovery:
            return PodAnalyzerBinding(None, "kubernetes_source_unbound")
        if identity is None and (
            config.kubernetes_subscription_discovery
            or any(
                binding.auth_mode == "workload-identity" for binding in config.kubernetes_bindings
            )
        ):
            return PodAnalyzerBinding(None, "kubernetes_workload_identity_unbound")
        catalog = load_provider_relationship_mapping_catalog(
            repo_asset_root() / "rule-catalog" / "vocabulary" / "provider-relationship-mappings"
        )
        inventory = PostgresPromotedInventoryGenerationReader(
            config=PostgresInventorySnapshotStoreConfig(dsn=config.dsn)
        )
        history = PostgresKubernetesLifecycleStore(
            config=PostgresKubernetesLifecycleConfig(dsn=config.dsn)
        )
        source: LivePodLifecycleEvidenceSource | _CachedPodEvidenceSource
        if config.kubernetes_bindings:
            collectors = await _collectors(config, config.kubernetes_bindings, stack, identity)
            source = LivePodLifecycleEvidenceSource(
                inventory=inventory,
                collectors=collectors,
                relationship_mapping_catalog=catalog,
                lifecycle_store=history,
                lifecycle_cluster_refs={
                    to_neutral_id(binding.cluster_ref): binding.cluster_ref
                    for binding in config.kubernetes_bindings
                },
                freshness_seconds=config.freshness_budget_seconds,
            )
        else:
            cache_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=config.dsn))
            stack.push_async_callback(cache_store.aclose)
            source = _CachedPodEvidenceSource(
                config=config,
                inventory=inventory,
                cache=StateStoreAksSubscriptionBindingCache(cache_store),
                history=history,
                catalog=catalog,
                identity=identity,
            )
        stack.push_async_callback(source.aclose)
        return PodAnalyzerBinding(PodRecoveryAnalyzer(KubernetesPodFailureAnalyzer(source)))
    except PodEvidenceUnavailableError as exc:
        return PodAnalyzerBinding(None, exc.reason)
    except (ValueError, RuntimeError, OSError):
        return PodAnalyzerBinding(None, "kubernetes_source_configuration_invalid")


async def _collectors(
    config: InventoryJobConfig,
    bindings: tuple[KubernetesClusterBinding, ...],
    stack: AsyncExitStack,
    identity: WorkloadIdentity | None,
) -> dict[str, KubernetesApiInventorySource]:
    result: dict[str, KubernetesApiInventorySource] = {}
    for binding in bindings:
        _admit_cluster(config, binding.cluster_ref)
        tls = ssl.create_default_context(
            cafile=str(binding.ca_path) if binding.ca_path else None, cadata=binding.ca_pem
        )
        auth: KubernetesApiAuth
        if binding.auth_mode == "workload-identity":
            if identity is None or binding.audience is None:
                raise PodEvidenceUnavailableError("kubernetes_workload_identity_unbound")
            auth = WorkloadIdentityKubernetesAuth(identity=identity, audience=binding.audience)
        else:
            if binding.token_path is None:
                raise PodEvidenceUnavailableError("kubernetes_token_path_unbound")
            auth = ServiceAccountTokenAuth(binding.token_path)
        client = await stack.enter_async_context(
            httpx.AsyncClient(verify=tls, trust_env=False, follow_redirects=False)
        )
        neutral = to_neutral_id(binding.cluster_ref)
        if neutral in result:
            raise PodEvidenceUnavailableError(
                "kubernetes_cluster_binding_conflict", status="conflicting"
            )
        result[neutral] = KubernetesApiInventorySource(
            config=KubernetesApiInventoryConfig(api_server=binding.api_server, cluster_ref=neutral),
            auth=auth,
            http_client=client,
        )
    return result


def _admit_cluster(config: InventoryJobConfig, cluster_ref: str) -> None:
    parts = cluster_ref.split("/")
    if len(parts) < 3 or parts[1].casefold() != "subscriptions":
        raise PodEvidenceUnavailableError(
            "kubernetes_cluster_identity_invalid", status="conflicting"
        )
    if parts[2].casefold() not in {scope.casefold() for scope in config.scopes}:
        raise PodEvidenceUnavailableError("kubernetes_cluster_outside_inventory_scope")


class _PinnedInventory:
    def __init__(self, generation: PromotedInventoryGeneration) -> None:
        self._generation = generation

    async def active_generation_id(self) -> str:
        return self._generation.generation

    async def load_active_generation(self, *, max_resources: int) -> PromotedInventoryGeneration:
        if len(self._generation.resources) > max_resources:
            raise PodEvidenceUnavailableError("pod_resource_limit", status="partial")
        return self._generation


class _CachedPodEvidenceSource:
    """Resolve only a requested promoted cluster's existing public binding cache."""

    def __init__(
        self,
        *,
        config: InventoryJobConfig,
        inventory: PromotedInventoryGenerationReader,
        cache: StateStoreAksSubscriptionBindingCache,
        history: PostgresKubernetesLifecycleStore,
        catalog: ProviderRelationshipMappingCatalog,
        identity: WorkloadIdentity | None,
    ) -> None:
        self._config = config
        self._inventory = inventory
        self._cache = cache
        self._history = history
        self._catalog = catalog
        self._identity = identity
        self._tick = PodTickCache(timeout_seconds=60)
        self._sources = AsyncExitStack()

    async def aclose(self) -> None:
        await self._tick.aclose()
        await self._sources.aclose()

    async def observe(
        self, *, resource_ref: str, window_seconds: float
    ) -> PodLifecycleEvidence | None:
        return (
            await self.observe_pod(resource_ref=resource_ref, window_seconds=window_seconds)
        ).lifecycle

    async def observe_status(
        self, *, resource_ref: str, window_seconds: float
    ) -> PodStatusEvidence | None:
        return (
            await self.observe_pod(resource_ref=resource_ref, window_seconds=window_seconds)
        ).status

    async def observe_pod(self, *, resource_ref: str, window_seconds: float) -> PodFailureEvidence:
        try:
            async with asyncio.timeout(60):
                generation = await self._tick.read(
                    ("inventory",),
                    lambda: read_inventory(self._inventory, max_resources=20_000),
                )
                if generation is None or not generation.complete:
                    raise PodEvidenceUnavailableError("inventory_generation_unavailable")
                pods = [
                    record
                    for record in generation.resources
                    if record.resource_id == resource_ref and record.type == "kubernetes.pod"
                ]
                if len(pods) != 1:
                    raise PodEvidenceUnavailableError("inventory_pod_identity_unavailable")
                neutral = text(pods[0].props, "cluster_ref")
                clusters = [
                    record
                    for record in generation.resources
                    if record.resource_id == neutral and record.type == "kubernetes-cluster"
                ]
                if len(clusters) != 1 or not clusters[0].provider_ref:
                    raise PodEvidenceUnavailableError("inventory_cluster_identity_unavailable")
                provider_ref = clusters[0].provider_ref
                if to_neutral_id(provider_ref) != neutral:
                    raise PodEvidenceUnavailableError(
                        "inventory_cluster_identity_conflict", status="conflicting"
                    )
                _admit_cluster(self._config, provider_ref)
                source = await self._tick.read(
                    ("source", generation.generation, neutral, provider_ref),
                    lambda: self._source_for_cluster(generation, neutral, provider_ref),
                )
                return await source.observe_pod(
                    resource_ref=resource_ref, window_seconds=window_seconds
                )
        except PodEvidenceUnavailableError:
            raise
        except TimeoutError:
            raise PodEvidenceUnavailableError("pod_read_deadline_exceeded") from None
        except Exception:  # noqa: BLE001 - never disclose DB, endpoint or credential errors
            raise PodEvidenceUnavailableError("pod_source_read_failed") from None

    async def _source_for_cluster(
        self, generation: PromotedInventoryGeneration, neutral: str, provider_ref: str
    ) -> LivePodLifecycleEvidenceSource:
        cached = await self._cache.read(provider_ref)
        if cached is None:
            raise PodEvidenceUnavailableError("kubernetes_binding_cache_unavailable")
        now = datetime.now(UTC)
        if cached.cluster_ref.casefold() != provider_ref.casefold() or cached.observed_at > now:
            raise PodEvidenceUnavailableError(
                "kubernetes_binding_cache_conflict", status="conflicting"
            )
        if (now - cached.observed_at).total_seconds() > self._config.freshness_budget_seconds:
            raise PodEvidenceUnavailableError("kubernetes_binding_cache_stale", status="stale")
        binding = cached.to_binding()
        collectors = await _collectors(self._config, (binding,), self._sources, self._identity)
        source = LivePodLifecycleEvidenceSource(
            inventory=_PinnedInventory(generation),
            collectors=collectors,
            relationship_mapping_catalog=self._catalog,
            lifecycle_store=self._history,
            lifecycle_cluster_refs={neutral: binding.cluster_ref},
            freshness_seconds=self._config.freshness_budget_seconds,
        )
        self._sources.push_async_callback(source.aclose)
        return source
