"""Inventory job configuration boundary tests."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import yaml
from fdai.delivery import inventory_sync_cli_support
from fdai.delivery.aks_subscription_discovery import (
    AksSubscriptionDiscoveryError,
    AksSubscriptionDiscoveryResult,
)
from fdai.delivery.azure.arg_projection import to_neutral_id
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.inventory import AzureResourceGraphInventory
from fdai.delivery.azure.model_serving_inventory import AzureModelServingInventoryEnricher
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.inventory_change_acceleration import (
    forward_recovery_deltas as _forward_recovery_deltas,
)
from fdai.delivery.inventory_collection import collection_context_digest, collection_producer_digest
from fdai.delivery.inventory_job_config import (
    InventoryJobConfig,
    inventory_scopes_from_env,
    verify_declarative_sha256,
)
from fdai.delivery.inventory_ontology_observer import (
    build_ontology_observer as _build_ontology_observer,
)
from fdai.delivery.inventory_scheduler import (
    CollectionScheduleAction,
    CollectionScheduleDecision,
    ProviderPressure,
)
from fdai.delivery.inventory_sync import (
    InventoryPromotionObserverError,
    PromotedInventoryObservation,
)
from fdai.delivery.inventory_sync_cli import (
    ChangeStreamDrainResult,
    _build_kubernetes_enricher,
    _build_runtime_call_enricher,
    _build_sources,
    _collect_kubernetes_lifecycle,
    _drain_change_stream,
    _load_relationship_mapping_catalog,
    _main,
    _publish_collection_health,
    _resolve_resource_types,
    _resolve_subscription_kubernetes_bindings,
    _run_due_once,
    _workload_identity,
    container_argv,
    run,
)
from fdai.delivery.kubernetes_api_inventory import KubernetesApiInventoryConfig
from fdai.delivery.kubernetes_cluster_binding import KubernetesClusterBinding
from fdai.delivery.kubernetes_inventory import (
    SequentialInventoryPromotionEnricher,
    UnavailableKubernetesInventoryEnricher,
)
from fdai.delivery.operational_activity import EventBusOperationalActivityPublisher
from fdai.delivery.persistence.postgres_inventory_reconciliation import (
    InventoryReconciliationHealthState,
)
from fdai.delivery.runtime_call_inventory import (
    RuntimeCallInventoryEnricher,
    UnavailableRuntimeCallInventoryEnricher,
)
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    load_resource_type_registry_from_mapping,
)
from fdai.runtime.inventory_ontology import InventoryOntologyProjectionStatus
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.inventory_snapshot import InventorySourcesExhaustedError
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity
from fdai_service_contracts import OperationalActivityStatus

_REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    "extra",
    [
        {"FDAI_KUBERNETES_CONNECTOR_REGISTRATION_PATH": "/example/registrations.json"},
        {"FDAI_KUBERNETES_CONNECTOR_CLUSTER_RESOURCES": "1"},
        {
            "FDAI_KUBERNETES_CONNECTOR_REGISTRATION_PATH": "/example/registrations.json",
            "FDAI_KUBERNETES_CONNECTOR_PRINCIPAL_REF": "example",
            "FDAI_KUBERNETES_SUBSCRIPTION_DISCOVERY": "1",
        },
    ],
)
def test_connector_rejects_incomplete_or_mixed_inventory_binding(extra: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="connector"):
        InventoryJobConfig.from_env(
            {
                "FDAI_INVENTORY_DSN": "postgresql://example",
                "FDAI_INVENTORY_SCOPES": "00000000-0000-0000-0000-000000000000",
                **extra,
            }
        )


_CLUSTER_REF = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/"
    "providers/Microsoft.ContainerService/managedClusters/aks-example"
)


def _vocabulary() -> ResourceTypeRegistry:
    path = _REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
    return load_resource_type_registry_from_mapping(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )


def test_inventory_scopes_prefer_authoritative_multi_scope_setting() -> None:
    assert inventory_scopes_from_env(
        {
            "AZURE_SUBSCRIPTION_ID": "legacy-scope",
            "FDAI_INVENTORY_SCOPES": "scope-b, scope-a, scope-b",
        }
    ) == ("scope-b", "scope-a")
    assert inventory_scopes_from_env({"AZURE_SUBSCRIPTION_ID": "legacy-scope"}) == ("legacy-scope",)


def _state_store_double() -> SimpleNamespace:
    from fdai.shared.providers.testing import InMemoryStateStore

    store = InMemoryStateStore()
    return SimpleNamespace(
        read_state=AsyncMock(wraps=store.read_state),
        write_state=AsyncMock(wraps=store.write_state),
        write_state_if_absent=AsyncMock(wraps=store.write_state_if_absent),
        write_state_with_audit_if_absent=AsyncMock(return_value=True),
    )


def _ontology_observer_harness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    operator_requested: bool = False,
) -> tuple[Any, ...]:
    config_values = {
        "FDAI_INVENTORY_DSN": "postgresql://example",
        "AZURE_SUBSCRIPTION_ID": "sub-1",
    }
    if operator_requested:
        config_values["FDAI_INVENTORY_OPERATOR_REQUESTED"] = "1"
    config = InventoryJobConfig.from_env(config_values)
    from fdai.delivery import inventory_ontology_observer
    from fdai.shared.providers.testing import InMemoryStateStore

    if isinstance(inventory_ontology_observer.PostgresStateStore, type):
        status_store = InMemoryStateStore()
        monkeypatch.setattr(
            inventory_ontology_observer, "PostgresStateStore", lambda **_: status_store
        )
    ontology_store = SimpleNamespace(
        sync_catalog=AsyncMock(),
        read_inventory_state_base=AsyncMock(return_value=()),
    )
    history_store = SimpleNamespace(append=AsyncMock(), read=AsyncMock(return_value=()))
    projector = SimpleNamespace(
        construction_kwargs={},
        apply=AsyncMock(
            return_value=SimpleNamespace(
                status=InventoryOntologyProjectionStatus.AVAILABLE,
                object_count=1,
                link_count=0,
                complete=True,
                dropped_reasons=(),
            )
        ),
    )
    release_digest = "sha256:" + ("a" * 64)
    catalog = SimpleNamespace(
        object_types=(),
        link_types=(),
        build_release=lambda: SimpleNamespace(digest=release_digest),
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_ontology_observer.load_ontology_catalog",
        lambda *a, **k: catalog,
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_ontology_observer.PostgresOntologyInstanceStore",
        lambda **_: ontology_store,
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_ontology_observer.PostgresTopologyHistoryStore",
        lambda **_: history_store,
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_ontology_observer.InventoryOntologyProjector",
        lambda **kwargs: projector.construction_kwargs.update(kwargs) or projector,
    )
    observation_journal = SimpleNamespace(
        append_promoted_snapshot=AsyncMock(
            return_value=SimpleNamespace(
                journal_high_watermark=7,
                projection_high_watermark=7,
                active_scope_projection_watermark=7,
                active_scope_refs=("scope-1",),
            )
        ),
        mark_ontology_projected=AsyncMock(),
        load_pending_promoted_snapshot=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_ontology_observer.build_observation_journal",
        lambda *_args, **_kwargs: observation_journal,
    )
    configuration_event_publisher = AsyncMock(return_value=1)
    monkeypatch.setattr(
        "fdai.delivery.inventory_ontology_observer.PostgresInventoryDeliveryReader",
        lambda **_: SimpleNamespace(load_next=AsyncMock(return_value=None)),
    )
    activity_publisher = SimpleNamespace(
        publish=AsyncMock(),
        configuration_event_publisher=configuration_event_publisher,
    )
    observer, recovery = _build_ontology_observer(
        config,
        vocabulary=_vocabulary(),
        publisher=cast(EventBusOperationalActivityPublisher, activity_publisher),
        configuration_event_publisher=configuration_event_publisher,
        evidence_counts={},
    )
    return (
        observer,
        recovery,
        observation_journal,
        ontology_store,
        history_store,
        projector,
        activity_publisher,
        release_digest,
    )


def _promoted_observation(generation: str) -> PromotedInventoryObservation:
    return PromotedInventoryObservation(
        generation=generation,
        resources=(ResourceRecord(resource_id="vm-1", type="compute.vm"),),
        links=(),
        complete=True,
        recorded_at=datetime(2026, 8, 13, tzinfo=UTC),
    )


def _http_ok(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={})


def test_job_config_defaults_to_arg_then_arm() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )

    assert config.source_order == ("arg", "arm")
    assert config.operator_requested is False


def test_job_config_accepts_one_shot_operator_reconciliation_request() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "FDAI_INVENTORY_OPERATOR_REQUESTED": "1",
        }
    )

    assert config.operator_requested is True
    assert config.scopes == ("sub-1",)
    assert config.freshness_budget_seconds == 86_400
    assert config.reconciliation_interval_seconds == 21_600
    assert config.management_audience == "https://management.azure.com/.default"
    assert config.loop_seconds == 60
    assert config.change_min_interval_seconds == 120
    assert config.progress_deadline_seconds == 900
    assert config.attempt_deadline_seconds == 1500
    assert config.arg_requests_per_second == 3.0
    assert config.recovery_delta_enabled is True
    assert config.resource_change_feed_enabled is True
    assert config.kubernetes_api_server is None
    assert config.kubernetes_cluster_ref is None
    assert config.kubernetes_token_path is None
    assert config.kubernetes_ca_path is None
    assert config.kubernetes_ca_pem is None
    assert config.kubernetes_auth_mode is None
    assert config.monitor_workspace_id is None
    assert config.runtime_call_evidence_enabled is False
    assert config.snapshot_policy("arg").max_requests_per_window == 180
    assert config.collection_policy is not None


def test_job_config_binds_bounded_monitor_workspace_for_runtime_calls() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "FDAI_MONITOR_WORKSPACE_ID": "workspace-example",
            "FDAI_RUNTIME_CALL_EVIDENCE_ENABLED": "1",
        }
    )

    assert config.monitor_workspace_id == "workspace-example"
    assert config.runtime_call_evidence_enabled is True

    with pytest.raises(ValueError, match="MUST be bounded printable text"):
        InventoryJobConfig.from_env(
            {
                "FDAI_INVENTORY_DSN": "postgresql://example",
                "AZURE_SUBSCRIPTION_ID": "sub-1",
                "FDAI_MONITOR_WORKSPACE_ID": "workspace with spaces",
            }
        )
    with pytest.raises(ValueError, match="requires FDAI_MONITOR_WORKSPACE_ID"):
        InventoryJobConfig.from_env(
            {
                "FDAI_INVENTORY_DSN": "postgresql://example",
                "AZURE_SUBSCRIPTION_ID": "sub-1",
                "FDAI_RUNTIME_CALL_EVIDENCE_ENABLED": "1",
            }
        )


async def test_runtime_call_enricher_requires_deployed_explicit_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = StaticWorkloadIdentity(
        audience="https://api.loganalytics.io/.default",
        token="test-token",
    )
    monkeypatch.setenv("FDAI_EXECUTION_VENUE", "local")
    async with httpx.AsyncClient(transport=httpx.MockTransport(_http_ok)) as client:
        unavailable = _build_runtime_call_enricher(
            config=InventoryJobConfig.from_env(
                {
                    "FDAI_INVENTORY_DSN": "postgresql://example",
                    "AZURE_SUBSCRIPTION_ID": "sub-1",
                }
            ),
            identity=identity,
            http_client=client,
        )
        local_candidate = _build_runtime_call_enricher(
            config=InventoryJobConfig.from_env(
                {
                    "FDAI_INVENTORY_DSN": "postgresql://example",
                    "AZURE_SUBSCRIPTION_ID": "sub-1",
                    "FDAI_MONITOR_WORKSPACE_ID": "workspace-example",
                    "FDAI_RUNTIME_CALL_EVIDENCE_ENABLED": "1",
                }
            ),
            identity=identity,
            http_client=client,
        )
        monkeypatch.setenv("FDAI_EXECUTION_VENUE", "deployed")
        available = _build_runtime_call_enricher(
            config=InventoryJobConfig.from_env(
                {
                    "FDAI_INVENTORY_DSN": "postgresql://example",
                    "AZURE_SUBSCRIPTION_ID": "sub-1",
                    "FDAI_MONITOR_WORKSPACE_ID": "workspace-example",
                    "FDAI_RUNTIME_CALL_EVIDENCE_ENABLED": "1",
                }
            ),
            identity=identity,
            http_client=client,
        )

    assert isinstance(unavailable, UnavailableRuntimeCallInventoryEnricher)
    assert isinstance(local_candidate, UnavailableRuntimeCallInventoryEnricher)
    assert isinstance(available, RuntimeCallInventoryEnricher)


async def test_model_serving_enricher_matches_full_reconciliation_cadence() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "FDAI_INVENTORY_RECONCILIATION_INTERVAL_SECONDS": "21600",
        }
    )
    identity = StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="test-token",  # noqa: S106 - deterministic test credential
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(_http_ok)) as client:
        enrichers = inventory_sync_cli_support.build_azure_inventory_enrichers(
            config=config,
            identity=identity,
            http_client=client,
            previous_state_reader=cast(Any, SimpleNamespace()),
        )

    serving = enrichers[1]
    assert isinstance(serving, AzureModelServingInventoryEnricher)
    assert serving._config.lookback_seconds == config.reconciliation_interval_seconds  # noqa: SLF001
    assert (  # noqa: SLF001
        serving._config.freshness_ceiling_seconds == config.reconciliation_interval_seconds
    )
    assert serving._config.max_points_per_target == 361  # noqa: SLF001

    longer = replace(config, reconciliation_interval_seconds=43_200)
    async with httpx.AsyncClient(transport=httpx.MockTransport(_http_ok)) as client:
        long_interval_enrichers = inventory_sync_cli_support.build_azure_inventory_enrichers(
            config=longer,
            identity=identity,
            http_client=client,
            previous_state_reader=cast(Any, SimpleNamespace()),
        )
    long_serving = long_interval_enrichers[1]
    assert isinstance(long_serving, AzureModelServingInventoryEnricher)
    assert long_serving._config.lookback_seconds == 21_600  # noqa: SLF001
    assert long_serving._config.freshness_ceiling_seconds == 43_200  # noqa: SLF001


async def test_ontology_observer_persists_diagnostics_on_inventory_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_store = _state_store_double()
    monkeypatch.setattr(
        "fdai.delivery.inventory_ontology_observer.PostgresStateStore",
        lambda **_: state_store,
    )
    observer = _ontology_observer_harness(monkeypatch)[0]
    await observer(
        PromotedInventoryObservation(
            generation="snapshot-diagnostic",
            resources=(
                ResourceRecord(
                    resource_id="cluster/kubernetes/kubernetes.pod/default/api",
                    type="kubernetes.pod",
                    props={
                        "cluster_ref": "cluster",
                        "uid": "uid-api",
                        "resource_version": "20",
                    },
                ),
            ),
            links=(),
            complete=True,
            recorded_at=datetime(2026, 8, 13, tzinfo=UTC),
        )
    )

    state_store.write_state_with_audit_if_absent.assert_awaited_once()
    persisted_key = state_store.write_state_with_audit_if_absent.await_args.args[0]
    assert persisted_key.startswith("aks-diagnostic-receipt:v1:")


async def test_recovery_persists_diagnostics_without_ontology_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_store = SimpleNamespace(
        write_state_with_audit_if_absent=AsyncMock(return_value=True),
        read_state=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_ontology_observer.PostgresStateStore",
        lambda **_: state_store,
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_ontology_observer.read_bool_env",
        lambda *_args, **_kwargs: False,
    )
    _, recovery, observation_journal, *_ = _ontology_observer_harness(monkeypatch)
    observation_journal.load_pending_promoted_snapshot.return_value = PromotedInventoryObservation(
        generation="snapshot-recovery-diagnostic",
        resources=(
            ResourceRecord(
                resource_id="cluster/kubernetes/kubernetes.pod/default/api",
                type="kubernetes.pod",
                props={
                    "cluster_ref": "cluster",
                    "uid": "uid-api",
                    "resource_version": "20",
                },
            ),
        ),
        links=(),
        complete=True,
        recorded_at=datetime(2026, 8, 13, tzinfo=UTC),
    )

    await recovery()

    state_store.write_state_with_audit_if_absent.assert_awaited_once()
    observation_journal.append_promoted_snapshot.assert_awaited_once()


def test_default_inventory_scope_includes_llm_model_deployments() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )

    resource_types = _resolve_resource_types(config, _vocabulary())

    assert "llm-endpoint" in resource_types
    assert "llm-model-deployment" in resource_types


def test_inventory_run_exposes_pre_promotion_single_writer_enrichment() -> None:
    parameter = inspect.signature(run).parameters["promotion_enricher"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None


async def test_inventory_job_selects_only_the_venue_specific_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IDENTITY_ENDPOINT", "https://identity.example/token")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")
    async with httpx.AsyncClient(transport=httpx.MockTransport(_http_ok)) as client:
        monkeypatch.setenv("FDAI_EXECUTION_VENUE", "local")
        local = _workload_identity(http_client=client)
        monkeypatch.setenv("FDAI_EXECUTION_VENUE", "deployed")
        deployed = _workload_identity(http_client=client)

    assert isinstance(local, AsyncAzureCliWorkloadIdentity)
    assert isinstance(deployed, ManagedIdentityWorkloadIdentity)


async def test_lifecycle_collection_skips_an_unconfigured_source() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )

    assert await _collect_kubernetes_lifecycle(config) == 0


async def test_lifecycle_collection_visits_every_fleet_binding_and_preserves_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fleet = json.dumps(
        [
            {
                "api_server": "https://one.example",
                "cluster_ref": _CLUSTER_REF,
                "auth_mode": "service-account",
                "ca_path": "/var/run/fdai/one-ca.crt",
                "token_path": "/var/run/fdai/one-token",
            },
            {
                "api_server": "https://two.example",
                "cluster_ref": _CLUSTER_REF.replace("aks-example", "aks-two"),
                "auth_mode": "service-account",
                "ca_path": "/var/run/fdai/two-ca.crt",
                "token_path": "/var/run/fdai/two-token",
            },
        ]
    )
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "FDAI_KUBERNETES_CLUSTER_BINDINGS_JSON": fleet,
        }
    )
    calls: list[str] = []

    async def collect(binding: KubernetesClusterBinding, **_kwargs: Any) -> int | None:
        calls.append(binding.scope_digest)
        return 2 if len(calls) == 1 else None

    monkeypatch.setattr(
        inventory_sync_cli_support,
        "_collect_kubernetes_binding_lifecycle",
        collect,
    )

    assert await _collect_kubernetes_lifecycle(config) is None
    assert calls == [binding.scope_digest for binding in config.kubernetes_bindings]


def test_job_loads_reviewed_kubernetes_relationship_mappings() -> None:
    catalog = _load_relationship_mapping_catalog()

    assert {
        mapping.mapping_id for mapping in catalog.mappings if mapping.provider == "kubernetes"
    } == {
        "kubernetes.agent-pool-contains-node",
        "kubernetes.cluster-contains-ingress-class",
        "kubernetes.cluster-contains-diagnostic-resource",
        "kubernetes.cluster-contains-namespace",
        "kubernetes.endpoint-slice-exposed-by-service",
        "kubernetes.endpoint-slice-routes-to-pod",
        "kubernetes.ingress-attached-to-class",
        "kubernetes.ingress-routes-to-service",
        "kubernetes.hpa-attached-to-daemon-set",
        "kubernetes.hpa-attached-to-deployment",
        "kubernetes.hpa-attached-to-replica-set",
        "kubernetes.hpa-attached-to-stateful-set",
        "kubernetes.namespace-contains-resource",
        "kubernetes.network-policy-selects-pod",
        "kubernetes.node-backed-by-vmss-vm",
        "kubernetes.pdb-selects-pod",
        "kubernetes.pod-depends-on-pvc",
        "kubernetes.pod-scheduled-on-node",
        "kubernetes.pvc-attached-to-pv",
        "kubernetes.pvc-depends-on-storage-class",
        "kubernetes.resource-owned-by-controller",
        "kubernetes.service-exposes-endpoints",
        "kubernetes.service-selects-pod",
    }


def test_job_config_requires_complete_kubernetes_binding() -> None:
    with pytest.raises(ValueError, match="requires API server"):
        InventoryJobConfig.from_env(
            {
                "FDAI_INVENTORY_DSN": "postgresql://example",
                "AZURE_SUBSCRIPTION_ID": "sub-1",
                "FDAI_KUBERNETES_API_SERVER": "https://kubernetes.example",
            }
        )

    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "FDAI_KUBERNETES_API_SERVER": "https://kubernetes.example",
            "FDAI_KUBERNETES_CLUSTER_REF": _CLUSTER_REF,
            "FDAI_KUBERNETES_TOKEN_PATH": "/var/run/secrets/kubernetes/token",
            "FDAI_KUBERNETES_CA_PATH": "/var/run/secrets/kubernetes/ca.crt",
        }
    )

    assert config.kubernetes_api_server == "https://kubernetes.example"
    assert config.kubernetes_cluster_ref == _CLUSTER_REF
    assert config.kubernetes_token_path == Path("/var/run/secrets/kubernetes/token")
    assert config.kubernetes_ca_path == Path("/var/run/secrets/kubernetes/ca.crt")
    assert config.kubernetes_auth_mode == "service-account"


def test_job_config_accepts_only_exclusive_subscription_discovery() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000001",
            "FDAI_KUBERNETES_SUBSCRIPTION_DISCOVERY": "1",
        }
    )

    assert config.kubernetes_subscription_discovery is True
    assert config.kubernetes_bindings == ()

    with pytest.raises(ValueError, match="MUST NOT be combined"):
        InventoryJobConfig.from_env(
            {
                "FDAI_INVENTORY_DSN": "postgresql://example",
                "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000001",
                "FDAI_KUBERNETES_SUBSCRIPTION_DISCOVERY": "1",
                "FDAI_KUBERNETES_CLUSTER_BINDINGS_JSON": json.dumps(
                    [
                        {
                            "api_server": "https://one.example",
                            "cluster_ref": _CLUSTER_REF,
                            "auth_mode": "service-account",
                            "ca_path": "/var/run/fdai/ca.crt",
                            "token_path": "/var/run/fdai/token",
                        }
                    ]
                ),
            }
        )


async def test_subscription_discovery_result_is_applied_to_the_inventory_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000001",
            "FDAI_KUBERNETES_SUBSCRIPTION_DISCOVERY": "1",
        }
    )
    binding = KubernetesClusterBinding(
        api_server="https://aks.example",
        cluster_ref=_CLUSTER_REF,
        auth_mode="workload-identity",
        ca_pem="-----BEGIN CERTIFICATE-----\nexample\n-----END CERTIFICATE-----\n",
        audience="aks-audience",
    )
    discovery = Mock()
    discovery.discover = AsyncMock(
        return_value=AksSubscriptionDiscoveryResult(
            bindings=(binding,),
            unavailable_scopes=(),
        )
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.AzureAksSubscriptionBindingDiscovery",
        lambda **_kwargs: discovery,
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli._workload_identity",
        lambda **_kwargs: Mock(),
    )

    resolved = await _resolve_subscription_kubernetes_bindings(config)

    assert resolved.kubernetes_bindings == (binding,)
    assert resolved.kubernetes_unavailable_scopes == ()


async def test_subscription_discovery_failure_is_explicitly_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000001",
            "FDAI_KUBERNETES_SUBSCRIPTION_DISCOVERY": "1",
        }
    )
    discovery = Mock()
    discovery.discover = AsyncMock(
        side_effect=AksSubscriptionDiscoveryError("provider unavailable")
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.AzureAksSubscriptionBindingDiscovery",
        lambda **_kwargs: discovery,
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli._workload_identity",
        lambda **_kwargs: Mock(),
    )

    resolved = await _resolve_subscription_kubernetes_bindings(config)

    assert resolved.kubernetes_bindings == ()
    assert len(resolved.kubernetes_unavailable_scopes) == 1
    assert (
        resolved.kubernetes_unavailable_scopes[0].reason
        == "kubernetes_subscription_discovery_unavailable"
    )


async def test_unconfigured_kubernetes_composition_records_explicit_unavailability() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )

    async with AsyncExitStack() as stack:
        enricher = await _build_kubernetes_enricher(
            config=config,
            relationship_catalog=_load_relationship_mapping_catalog(),
            stack=stack,
        )
        enriched = await enricher.enrich(_promoted_observation("generation-unconfigured"))

    assert isinstance(enricher, UnavailableKubernetesInventoryEnricher)
    assert enriched.source_states[-1].source == "kubernetes_runtime_inventory"
    assert enriched.source_states[-1].reason == "kubernetes_source_unconfigured"


async def test_configured_kubernetes_composition_binds_exact_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "FDAI_KUBERNETES_API_SERVER": "https://kubernetes.example",
            "FDAI_KUBERNETES_CLUSTER_REF": _CLUSTER_REF,
            "FDAI_KUBERNETES_TOKEN_PATH": "/var/run/secrets/kubernetes/token",
            "FDAI_KUBERNETES_CA_PATH": "/var/run/secrets/kubernetes/ca.crt",
        }
    )
    fake_http_client = object()

    @asynccontextmanager
    async def _client_context() -> AsyncIterator[object]:
        yield fake_http_client

    source_factory = Mock(return_value=object())
    expected_enricher = UnavailableKubernetesInventoryEnricher()
    enricher_factory = Mock(return_value=expected_enricher)
    tls_factory = Mock(return_value=object())
    http_factory = Mock(return_value=_client_context())
    monkeypatch.setattr("fdai.delivery.inventory_sync_cli.ssl.create_default_context", tls_factory)
    monkeypatch.setattr("fdai.delivery.inventory_sync_cli.httpx.AsyncClient", http_factory)
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.KubernetesApiInventorySource",
        source_factory,
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.KubernetesInventoryEnricher",
        enricher_factory,
    )

    catalog = _load_relationship_mapping_catalog()
    async with AsyncExitStack() as stack:
        enricher = await _build_kubernetes_enricher(
            config=config,
            relationship_catalog=catalog,
            stack=stack,
        )

    assert enricher is expected_enricher
    tls_factory.assert_called_once_with(
        cafile="/var/run/secrets/kubernetes/ca.crt",
        cadata=None,
    )
    source_kwargs = source_factory.call_args.kwargs
    assert source_kwargs["config"] == KubernetesApiInventoryConfig(
        api_server="https://kubernetes.example",
        cluster_ref=to_neutral_id(_CLUSTER_REF),
    )
    assert source_kwargs["auth"].token_path == Path("/var/run/secrets/kubernetes/token")
    assert source_kwargs["http_client"] is fake_http_client
    enricher_factory.assert_called_once_with(
        source=source_factory.return_value,
        relationship_mapping_catalog=catalog,
        scope_digest=config.kubernetes_bindings[0].scope_digest,
    )


def test_job_config_accepts_workload_identity_kubernetes_binding() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "FDAI_KUBERNETES_API_SERVER": "https://kubernetes.example",
            "FDAI_KUBERNETES_CLUSTER_REF": _CLUSTER_REF,
            "FDAI_KUBERNETES_AUTH_MODE": "workload-identity",
            "FDAI_KUBERNETES_CA_PEM": "-----BEGIN CERTIFICATE-----\nfixture\n",
            "FDAI_KUBERNETES_AUDIENCE": "api://aks-reader/.default",
        }
    )

    assert config.kubernetes_token_path is None
    assert config.kubernetes_ca_path is None
    assert config.kubernetes_ca_pem == "-----BEGIN CERTIFICATE-----\nfixture"
    assert config.kubernetes_auth_mode == "workload-identity"
    assert config.kubernetes_audience == "api://aks-reader/.default"


def test_job_config_accepts_fleet_bindings_and_rejects_legacy_overlap() -> None:
    fleet = json.dumps(
        [
            {
                "api_server": "https://one.example",
                "cluster_ref": _CLUSTER_REF,
                "auth_mode": "workload-identity",
                "ca_path": "/var/run/fdai/one-ca.crt",
                "audience": "api://aks-reader/.default",
            },
            {
                "api_server": "https://two.example",
                "cluster_ref": _CLUSTER_REF.replace("aks-example", "aks-two"),
                "auth_mode": "service-account",
                "ca_path": "/var/run/fdai/two-ca.crt",
                "token_path": "/var/run/fdai/two-token",
            },
        ]
    )
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "FDAI_KUBERNETES_CLUSTER_BINDINGS_JSON": fleet,
        }
    )

    assert len(config.kubernetes_bindings) == 2
    assert config.kubernetes_api_server is None
    with pytest.raises(ValueError, match="MUST NOT be combined"):
        InventoryJobConfig.from_env(
            {
                "FDAI_INVENTORY_DSN": "postgresql://example",
                "AZURE_SUBSCRIPTION_ID": "sub-1",
                "FDAI_KUBERNETES_CLUSTER_BINDINGS_JSON": fleet,
                "FDAI_KUBERNETES_API_SERVER": "https://legacy.example",
            }
        )


async def test_fleet_composition_builds_one_scoped_source_per_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fleet = json.dumps(
        [
            {
                "api_server": "https://one.example",
                "cluster_ref": _CLUSTER_REF,
                "auth_mode": "service-account",
                "ca_path": "/var/run/fdai/one-ca.crt",
                "token_path": "/var/run/fdai/one-token",
            },
            {
                "api_server": "https://two.example",
                "cluster_ref": _CLUSTER_REF.replace("aks-example", "aks-two"),
                "auth_mode": "service-account",
                "ca_path": "/var/run/fdai/two-ca.crt",
                "token_path": "/var/run/fdai/two-token",
            },
        ]
    )
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "FDAI_KUBERNETES_CLUSTER_BINDINGS_JSON": fleet,
        }
    )

    @asynccontextmanager
    async def _client_context() -> AsyncIterator[object]:
        yield object()

    source_factory = Mock(side_effect=(object(), object()))
    enricher_factory = Mock(
        side_effect=(
            UnavailableKubernetesInventoryEnricher(),
            UnavailableKubernetesInventoryEnricher(),
        )
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.ssl.create_default_context",
        Mock(return_value=object()),
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.httpx.AsyncClient",
        Mock(side_effect=(_client_context(), _client_context())),
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.KubernetesApiInventorySource",
        source_factory,
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.KubernetesInventoryEnricher",
        enricher_factory,
    )

    async with AsyncExitStack() as stack:
        enricher = await _build_kubernetes_enricher(
            config=config,
            relationship_catalog=_load_relationship_mapping_catalog(),
            stack=stack,
        )

    assert isinstance(enricher, SequentialInventoryPromotionEnricher)
    assert [call.kwargs["config"].cluster_ref for call in source_factory.call_args_list] == [
        to_neutral_id(binding.cluster_ref) for binding in config.kubernetes_bindings
    ]
    assert [call.kwargs["scope_digest"] for call in enricher_factory.call_args_list] == [
        binding.scope_digest for binding in config.kubernetes_bindings
    ]


def test_job_config_prefers_durable_freshness_setting() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "FDAI_INVENTORY_FRESHNESS_SECONDS": "86400",
        },
        runtime_values={"inventory.freshness_seconds": 600},
    )

    assert config.freshness_budget_seconds == 600


@pytest.mark.parametrize(
    ("endpoint", "audience"),
    [
        ("http://169.254.169.254", "https://management.azure.com/.default"),
        ("https://untrusted.example", "https://management.azure.com/.default"),
        ("https://management.azure.com/path", "https://management.azure.com/.default"),
        ("https://management.azure.com", "https://untrusted.example/.default"),
    ],
)
def test_job_config_rejects_unapproved_management_origin(
    endpoint: str,
    audience: str,
) -> None:
    with pytest.raises(ValueError, match="MANAGEMENT_(ENDPOINT|AUDIENCE)"):
        InventoryJobConfig.from_env(
            {
                "FDAI_INVENTORY_DSN": "postgresql://example",
                "AZURE_SUBSCRIPTION_ID": "sub-1",
                "FDAI_INVENTORY_MANAGEMENT_ENDPOINT": endpoint,
                "FDAI_INVENTORY_MANAGEMENT_AUDIENCE": audience,
            }
        )


@pytest.mark.parametrize("value", ["59", "invalid"])
def test_job_config_rejects_invalid_reconciliation_interval(value: str) -> None:
    with pytest.raises(ValueError, match="RECONCILIATION_INTERVAL_SECONDS"):
        InventoryJobConfig.from_env(
            {
                "FDAI_INVENTORY_DSN": "postgresql://example",
                "AZURE_SUBSCRIPTION_ID": "sub-1",
                "FDAI_INVENTORY_RECONCILIATION_INTERVAL_SECONDS": value,
            }
        )


def test_job_config_reads_continuous_scan_overrides() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "FDAI_INVENTORY_LOOP_SECONDS": "15",
            "FDAI_INVENTORY_CHANGE_MIN_INTERVAL_SECONDS": "300",
            "FDAI_INVENTORY_PROGRESS_DEADLINE_SECONDS": "300",
            "FDAI_INVENTORY_ATTEMPT_DEADLINE_SECONDS": "600",
            "FDAI_INVENTORY_ARG_REQUESTS_PER_SECOND": "1.5",
            "FDAI_INVENTORY_RECOVERY_DELTA": "0",
        }
    )

    assert config.loop_seconds == 15
    assert config.change_min_interval_seconds == 300
    assert config.progress_deadline_seconds == 300
    assert config.attempt_deadline_seconds == 600
    assert config.arg_requests_per_second == 1.5
    assert config.recovery_delta_enabled is False


def test_job_config_rejects_settings_outside_source_policy(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    policy_document = json.loads(
        (_REPO_ROOT / "config" / "inventory-collection-policy.json").read_text(encoding="utf-8")
    )
    arg_policy = next(
        source for source in policy_document["sources"] if source["source_id"] == "arg-snapshot"
    )
    arg_policy["max_staleness_seconds"] = 30_000
    policy_path.write_text(json.dumps(policy_document), encoding="utf-8")

    with pytest.raises(ValueError, match="freshness exceeds"):
        InventoryJobConfig.from_env(
            {
                "FDAI_INVENTORY_DSN": "postgresql://example",
                "AZURE_SUBSCRIPTION_ID": "sub-1",
                "FDAI_INVENTORY_COLLECTION_POLICY_PATH": str(policy_path),
            }
        )


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("FDAI_INVENTORY_LOOP_SECONDS", "4", "LOOP_SECONDS"),
        ("FDAI_INVENTORY_LOOP_SECONDS", "3601", "LOOP_SECONDS"),
        ("FDAI_INVENTORY_CHANGE_MIN_INTERVAL_SECONDS", "0", "CHANGE_MIN_INTERVAL"),
        ("FDAI_INVENTORY_CHANGE_MIN_INTERVAL_SECONDS", "21601", "CHANGE_MIN_INTERVAL"),
        ("FDAI_INVENTORY_PROGRESS_DEADLINE_SECONDS", "59", "PROGRESS_DEADLINE"),
        ("FDAI_INVENTORY_ATTEMPT_DEADLINE_SECONDS", "899", "ATTEMPT_DEADLINE"),
        ("FDAI_INVENTORY_ATTEMPT_DEADLINE_SECONDS", "1741", "ATTEMPT_DEADLINE"),
        ("FDAI_INVENTORY_ARG_REQUESTS_PER_SECOND", "0", "ARG_REQUESTS_PER_SECOND"),
        ("FDAI_INVENTORY_ARG_REQUESTS_PER_SECOND", "101", "ARG_REQUESTS_PER_SECOND"),
        ("FDAI_INVENTORY_ARG_REQUESTS_PER_SECOND", "fast", "ARG_REQUESTS_PER_SECOND"),
    ],
)
def test_job_config_rejects_out_of_range_continuous_settings(
    key: str,
    value: str,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        InventoryJobConfig.from_env(
            {
                "FDAI_INVENTORY_DSN": "postgresql://example",
                "AZURE_SUBSCRIPTION_ID": "sub-1",
                key: value,
            }
        )


async def test_change_stream_failure_degrades_without_stopping_the_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )

    async def _unavailable(_config: InventoryJobConfig) -> int:
        raise RuntimeError("activity log unavailable")

    async def _feed_unavailable(_config: InventoryJobConfig) -> int:
        raise RuntimeError("resource change feed unavailable")

    monkeypatch.setattr("fdai.delivery.inventory_sync_cli.run_recovery_delta", _unavailable)
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.run_resource_change_feed", _feed_unavailable
    )

    result = await _drain_change_stream(config)
    assert result.published == 0
    assert result.unavailable_sources == ("resourcechanges", "activity_log")


async def test_post_promotion_recovery_failure_degrades_without_stopping_the_tick() -> None:
    import logging

    from fdai.delivery.inventory_sync_cli_support import try_recovery_delta_operation

    async def _unavailable() -> int:
        raise RuntimeError("activity log row rejected")

    assert (
        await try_recovery_delta_operation(
            _unavailable, logger=logging.getLogger("fdai.delivery.inventory_sync_cli")
        )
        is None
    )


async def test_change_stream_is_skipped_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "FDAI_INVENTORY_RECOVERY_DELTA": "false",
            "FDAI_INVENTORY_RESOURCE_CHANGE_FEED": "false",
        }
    )
    called = False
    feed_called = False

    async def _record(_config: InventoryJobConfig) -> int:
        nonlocal called
        called = True
        return 3

    async def _record_feed(_config: InventoryJobConfig) -> int:
        nonlocal feed_called
        feed_called = True
        return 5

    monkeypatch.setattr("fdai.delivery.inventory_sync_cli.run_recovery_delta", _record)
    monkeypatch.setattr("fdai.delivery.inventory_sync_cli.run_resource_change_feed", _record_feed)

    result = await _drain_change_stream(config)
    assert result.published == 0
    assert result.unavailable_sources == ()
    assert called is False
    assert feed_called is False


async def test_change_stream_sums_both_accelerators_when_both_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )

    async def _recovery(_config: InventoryJobConfig) -> int:
        return 3

    async def _feed(_config: InventoryJobConfig) -> int:
        return 5

    monkeypatch.setattr("fdai.delivery.inventory_sync_cli.run_recovery_delta", _recovery)
    monkeypatch.setattr("fdai.delivery.inventory_sync_cli.run_resource_change_feed", _feed)

    result = await _drain_change_stream(config)
    assert result.published == 8
    assert result.unavailable_sources == ()


async def test_change_stream_one_failure_does_not_mask_the_other_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )

    async def _recovery_unavailable(_config: InventoryJobConfig) -> int:
        raise RuntimeError("activity log unavailable")

    async def _feed(_config: InventoryJobConfig) -> int:
        return 5

    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.run_recovery_delta", _recovery_unavailable
    )
    monkeypatch.setattr("fdai.delivery.inventory_sync_cli.run_resource_change_feed", _feed)

    result = await _drain_change_stream(config)
    assert result.published == 5
    assert result.unavailable_sources == ("activity_log",)


async def test_change_stream_invokes_resource_change_feed_before_recovery_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )
    call_order: list[str] = []

    async def _feed(_config: InventoryJobConfig) -> int:
        call_order.append("resource_change_feed")
        return 0

    async def _recovery(_config: InventoryJobConfig) -> int:
        call_order.append("recovery_delta")
        return 0

    monkeypatch.setattr("fdai.delivery.inventory_sync_cli.run_resource_change_feed", _feed)
    monkeypatch.setattr("fdai.delivery.inventory_sync_cli.run_recovery_delta", _recovery)

    result = await _drain_change_stream(config)
    assert result.published == 0
    assert result.unavailable_sources == ()
    assert call_order == ["resource_change_feed", "recovery_delta"]


async def test_not_due_tick_flushes_service_readiness_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )
    settings_store = SimpleNamespace(aclose=AsyncMock())
    runtime_settings = SimpleNamespace(
        effective_values=AsyncMock(return_value={}),
        store=settings_store,
    )
    printed = Mock()
    monkeypatch.setattr(
        "fdai.delivery.runtime_settings.runtime_settings_service_from_env",
        lambda _: runtime_settings,
    )
    monkeypatch.setattr(InventoryJobConfig, "from_env", lambda **_: config)
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli._drain_change_stream",
        AsyncMock(return_value=ChangeStreamDrainResult(published=0)),
    )
    gate = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.PostgresInventoryReconciliationGate",
        lambda **_: gate,
    )
    monkeypatch.setattr("builtins.print", printed)

    assert await _run_due_once() is config
    settings_store.aclose.assert_awaited_once_with()
    printed.assert_called_once_with(
        "inventory reconciliation not due; change records published 0",
        flush=True,
    )
    gate.assert_awaited_once_with(
        config.reconciliation_interval_seconds,
        operator_requested=False,
    )


async def test_disabled_accelerators_do_not_require_collection_policy_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )
    assert base_config.collection_policy is not None

    class _PolicyWithoutAccelerators:
        def source(self, source_id: str) -> object:
            if source_id in {"resourcechanges-delta", "activity-log-delta"}:
                raise AssertionError(f"disabled accelerator policy was read: {source_id}")
            return base_config.collection_policy.source(source_id)

    config = replace(
        base_config,
        resource_change_feed_enabled=False,
        recovery_delta_enabled=False,
        collection_policy=cast(Any, _PolicyWithoutAccelerators()),
    )
    captured: dict[str, object] = {}

    def gate(**kwargs: object) -> AsyncMock:
        captured.update(kwargs)
        return AsyncMock(return_value=False)

    monkeypatch.setattr(InventoryJobConfig, "from_env", lambda **_: config)
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli._drain_change_stream",
        AsyncMock(return_value=ChangeStreamDrainResult(published=0)),
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.PostgresInventoryReconciliationGate",
        gate,
    )

    await _run_due_once()

    assert captured["cursor_prefixes"] == ()
    assert captured["cursor_stale_after_seconds"] == 0.0


async def test_loop_retries_after_all_inventory_sources_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )
    attempts = 0

    class StopLoopError(RuntimeError):
        pass

    async def run_tick(_config: InventoryJobConfig) -> InventoryJobConfig:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise InventorySourcesExhaustedError(())
        raise StopLoopError

    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli._load_job_config",
        AsyncMock(return_value=config),
    )
    monkeypatch.setattr("fdai.delivery.inventory_sync_cli._run_due_once", run_tick)
    monkeypatch.setattr("fdai.delivery.inventory_sync_cli.asyncio.sleep", AsyncMock())

    with pytest.raises(StopLoopError):
        await _main(["--loop"])

    assert attempts == 2


async def test_loop_retries_after_ontology_projection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )
    attempts = 0

    class StopLoopError(RuntimeError):
        pass

    async def run_tick(_config: InventoryJobConfig) -> InventoryJobConfig:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise InventoryPromotionObserverError("projection failed")
        raise StopLoopError

    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli._load_job_config",
        AsyncMock(return_value=config),
    )
    monkeypatch.setattr("fdai.delivery.inventory_sync_cli._run_due_once", run_tick)
    monkeypatch.setattr("fdai.delivery.inventory_sync_cli.asyncio.sleep", AsyncMock())

    with pytest.raises(StopLoopError):
        await _main(["--loop"])

    assert attempts == 2


async def test_one_shot_propagates_all_inventory_sources_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli._load_job_config",
        AsyncMock(return_value=config),
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli._run_due_once",
        AsyncMock(side_effect=InventorySourcesExhaustedError(())),
    )

    with pytest.raises(InventorySourcesExhaustedError):
        await _main([])


async def test_initial_inventory_bypasses_recurring_due_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )
    run_once = AsyncMock()
    due_once = AsyncMock()
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli._load_job_config",
        AsyncMock(return_value=config),
    )
    monkeypatch.setattr("fdai.delivery.inventory_sync_cli.run", run_once)
    monkeypatch.setattr("fdai.delivery.inventory_sync_cli._run_due_once", due_once)

    await _main(["--initial"])

    run_once.assert_awaited_once_with(config)
    due_once.assert_not_awaited()


async def test_collection_health_persists_only_sanitized_aggregate_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )
    store = SimpleNamespace(write_state=AsyncMock(), aclose=AsyncMock())
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.PostgresStateStore",
        lambda **_: store,
    )
    health_state = InventoryReconciliationHealthState(
        measured_at=datetime(2026, 8, 22, 2, 0, tzinfo=UTC),
        evidence_age_seconds=300,
        resource_count=100,
        relationship_count=200,
        overlay_resource_count=3,
        overlay_relationship_count=5,
        cursor_lag_seconds=None,
        cursor_complete=False,
        coverage_complete=True,
        provider_pressure=ProviderPressure.THROTTLED,
        newer_failure=True,
    )
    decision = CollectionScheduleDecision(
        action=CollectionScheduleAction.WAIT,
        due_in_seconds=60,
        interval_seconds=60,
        priority=10,
        concurrency_limit=1,
        freshness_available=False,
        reason_codes=("provider_retry_after",),
    )

    await _publish_collection_health(
        config,
        health_state=health_state,
        decision=decision,
    )

    key, projection = store.write_state.await_args.args
    store.aclose.assert_awaited_once_with()
    assert key == "inventory-collection-health"
    assert projection["source_alias"] == "arg-snapshot"
    assert projection["cursor"]["state"] == "unavailable"
    assert projection["overlay"]["state"] == "open"
    assert projection["provider_pressure"]["state"] == "throttled"
    assert projection["next_action"]["reason_codes"] == ["provider_retry_after"]
    assert projection["coverage"]["gap_codes"] == [
        "cursor_unavailable",
        "overlay_incomplete",
        "source_unavailable",
    ]
    assert projection["execution_authority"] is False


def test_job_config_rejects_unsigned_declarative_fallback() -> None:
    with pytest.raises(ValueError, match="requires"):
        InventoryJobConfig.from_env(
            {
                "FDAI_INVENTORY_DSN": "postgresql://example",
                "AZURE_SUBSCRIPTION_ID": "sub-1",
                "FDAI_INVENTORY_SOURCES": "arg,declarative",
            }
        )


def test_declarative_sha_verification(tmp_path: Path) -> None:
    fixture = tmp_path / "inventory.yaml"
    fixture.write_text("resources: []\nlinks: []\n", encoding="utf-8")
    digest = hashlib.sha256(fixture.read_bytes()).hexdigest()

    verify_declarative_sha256(fixture, digest)
    with pytest.raises(ValueError, match="does not match"):
        verify_declarative_sha256(fixture, "0" * 64)


def test_resource_type_resolution_rejects_unknown_type() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "FDAI_INVENTORY_RESOURCE_TYPES": "compute.vm,unknown.type",
        }
    )

    with pytest.raises(ValueError, match="unknown inventory resource types"):
        _resolve_resource_types(config, _vocabulary())


@pytest.mark.parametrize(
    "change",
    [
        "same",
        "clock",
        "order",
        "endpoint",
        "audience",
        "rate",
        "policy",
        "mapping",
        "version",
        "kind",
        "arg_query",
    ],
)
async def test_source_context_binds_effective_collection_configuration(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    config = InventoryJobConfig.from_env(
        {"FDAI_INVENTORY_DSN": "postgresql://example", "AZURE_SUBSCRIPTION_ID": "sub-1"}
    )
    vocabulary = _vocabulary()
    identity = StaticWorkloadIdentity(
        audience=config.management_audience,
        token="synthetic",  # noqa: S106
    )
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    async with httpx.AsyncClient(transport=httpx.MockTransport(_http_ok)) as client:

        def build(configuration, registry, started):
            return _build_sources(
                config=configuration,
                vocabulary=registry,
                resource_types=("resource-group", "compute.vm"),
                identity=identity,
                http_client=client,
                started_at=started,
            )[0].manifest

        original = build(config, vocabulary, started_at)
        if change == "clock":
            started_at = datetime(2026, 1, 2, tzinfo=UTC)
        elif change == "order":
            vocabulary = vocabulary.model_copy(update={"types": tuple(reversed(vocabulary.types))})
        elif change == "endpoint":
            config = replace(config, management_endpoint="https://example.com")
        elif change == "audience":
            config = replace(config, management_audience="https://example.com/.default")
        elif change == "rate":
            config = replace(config, arg_requests_per_second=config.arg_requests_per_second / 2)
        elif change == "policy":
            original_policy = InventoryJobConfig.snapshot_policy
            monkeypatch.setattr(
                InventoryJobConfig,
                "snapshot_policy",
                lambda instance, source: replace(
                    original_policy(instance, source),
                    max_requests_per_window=original_policy(
                        instance, source
                    ).max_requests_per_window
                    + 1,
                ),
            )
        elif change == "arg_query":
            monkeypatch.setattr(
                "fdai.delivery.azure.arg_query.AzureArgQueryFactory.collection_contract_digest",
                property(lambda factory: "sha256:" + "a" * 64),
            )
        elif change == "version":
            vocabulary = vocabulary.model_copy(update={"version": "99.0.0"})
        elif change in {"mapping", "kind"}:
            update = (
                {"azure_arm_type": "Microsoft.Example/widgets"}
                if change == "mapping"
                else {"azure_kind_tokens": ("example",)}
            )
            vocabulary = vocabulary.model_copy(
                update={
                    "types": tuple(
                        entry.model_copy(update=update) if entry.id == "compute.vm" else entry
                        for entry in vocabulary
                    )
                }
            )
        modified = build(config, vocabulary, started_at)
    unchanged = change in {"same", "clock", "order"}
    assert (collection_context_digest(original) == collection_context_digest(modified)) is unchanged
    assert "management_endpoint" not in modified.metadata
    assert "management_audience" not in modified.metadata
    assert modified.metadata["collection_configuration_digest"].startswith("sha256:")
    assert modified.metadata["arg_query_contract_digest"].startswith("sha256:")


@pytest.mark.parametrize(
    "change", ["same", "source", "add", "delete", "rename", "symlink", "empty"]
)
def test_collection_producer_digest_pins_code_and_rejects_unavailable_source(tmp_path, change):
    source = tmp_path / "producer.py"
    source.write_text("revision = 1\n", encoding="utf-8")
    original = collection_producer_digest(tmp_path)
    if change == "source":
        source.write_text("revision = 2\n", encoding="utf-8")
    elif change == "add":
        (tmp_path / "overlay.py").write_text("revision = 1\n", encoding="utf-8")
    elif change in {"delete", "empty"}:
        source.unlink()
        if change == "delete":
            (tmp_path / "overlay.py").write_text("revision = 1\n", encoding="utf-8")
    elif change == "rename":
        source.rename(tmp_path / "renamed.py")
    elif change == "symlink":
        (tmp_path / "linked.py").symlink_to(source)
    if change in {"symlink", "empty"}:
        with pytest.raises(ValueError, match="inventory producer"):
            collection_producer_digest(tmp_path)
    else:
        assert (collection_producer_digest(tmp_path) == original) is (change == "same")


async def test_declarative_source_context_binds_verified_fixture_content(tmp_path: Path) -> None:
    fixture = tmp_path / "inventory.yaml"
    fixture.write_text("resources: []\nlinks: []\n", encoding="utf-8")
    config = replace(
        InventoryJobConfig.from_env(
            {"FDAI_INVENTORY_DSN": "postgresql://example", "AZURE_SUBSCRIPTION_ID": "sub-1"}
        ),
        source_order=("declarative",),
        declarative_path=fixture,
        declarative_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
    )
    vocabulary = _vocabulary()
    identity = StaticWorkloadIdentity(audience=config.management_audience, token="synthetic")  # noqa: S106
    async with httpx.AsyncClient(transport=httpx.MockTransport(_http_ok)) as client:
        arguments = dict(
            vocabulary=vocabulary,
            resource_types=("resource-group", "compute.vm"),
            identity=identity,
            http_client=client,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        original = _build_sources(config=config, **arguments)[0].manifest
        fixture.write_text("resources: []\nlinks: []\n# changed revision\n", encoding="utf-8")
        with pytest.raises(ValueError, match="does not match"):
            _build_sources(config=config, **arguments)
        updated = _build_sources(
            config=replace(
                config, declarative_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest()
            ),
            **arguments,
        )[0].manifest
    assert collection_context_digest(original) != collection_context_digest(updated)


async def test_source_builder_preserves_order_and_fallback_coverage() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )
    vocabulary = _vocabulary()
    identity = StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="test-token",  # noqa: S106 - deterministic test credential
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(_http_ok)) as client:
        sources = _build_sources(
            config=config,
            vocabulary=vocabulary,
            resource_types=("resource-group", "compute.vm"),
            identity=identity,
            http_client=client,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    assert tuple(source.name for source in sources) == ("arg", "arm")
    assert sources[0].manifest.metadata["link_types"] == (
        "contains",
        "attached_to",
        "depends_on",
        "peered_with",
        "routes_to",
    )
    assert isinstance(sources[0].inventory, AzureResourceGraphInventory)
    assert sources[0].inventory._scope_coverage is not None  # noqa: SLF001
    assert sources[0].inventory._unmapped_resources is not None  # noqa: SLF001
    assert sources[0].inventory._generation_relationships is not None  # noqa: SLF001
    assert sources[0].manifest.resource_types == (
        "resource-group",
        "compute.vm",
        "unclassified-resource",
    )
    assert sources[1].manifest.metadata["link_types"] == ("contains",)
    assert isinstance(sources[1].inventory, AzureResourceGraphInventory)
    assert sources[1].inventory._scope_coverage is None  # noqa: SLF001
    assert sources[1].inventory._unmapped_resources is None  # noqa: SLF001


async def test_source_builder_does_not_claim_full_provider_coverage_for_subset() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "FDAI_INVENTORY_RESOURCE_TYPES": "compute.vm",
        }
    )
    vocabulary = _vocabulary()
    identity = StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="test-token",  # noqa: S106 - deterministic test credential
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(_http_ok)) as client:
        sources = _build_sources(
            config=config,
            vocabulary=vocabulary,
            resource_types=_resolve_resource_types(config, vocabulary),
            identity=identity,
            http_client=client,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    assert sources[0].manifest.metadata["coverage_scope"] == "requested_resource_types"
    assert "unclassified-resource" not in sources[0].manifest.resource_types
    assert sources[0].inventory._scope_coverage is None  # noqa: SLF001
    assert sources[0].inventory._unmapped_resources is None  # noqa: SLF001


async def test_ontology_observer_publishes_durable_topology_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        observer,
        _recovery,
        _observation_journal,
        ontology_store,
        history_store,
        projector,
        _activity_publisher,
        release_digest,
    ) = _ontology_observer_harness(monkeypatch)

    await observer(_promoted_observation("snapshot-1"))

    history_store.append.assert_awaited_once()
    assert history_store.append.await_args.kwargs["ontology_release_digest"] == release_digest
    assert projector.construction_kwargs["freshness_ceiling_seconds"] == 21_600
    ontology_store.sync_catalog.assert_awaited_once()
    projector.apply.assert_awaited_once()
    assert projector.apply.await_args.kwargs["active_scope_projection_watermark"] == 7
    assert projector.apply.await_args.kwargs["active_scope_refs"] == ("scope-1",)
    _activity_publisher.configuration_event_publisher.assert_awaited_once_with(
        _promoted_observation("snapshot-1")
    )


async def test_ontology_observer_reuses_unchanged_history_and_configuration_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        observer,
        _recovery,
        observation_journal,
        _ontology_store,
        history_store,
        projector,
        activity_publisher,
        _release_digest,
    ) = _ontology_observer_harness(monkeypatch)
    observation_journal.append_promoted_snapshot.return_value.reused_journal_generation = (
        "snapshot-base"
    )
    observation = _promoted_observation("snapshot-unchanged")

    await observer(observation)

    history_store.append.assert_not_awaited()
    projector.apply.assert_awaited_once()
    activity_publisher.configuration_event_publisher.assert_not_awaited()
    store = projector.construction_kwargs["status_store"]
    delivery = await store.read_state("inventory-configuration:delivery")
    assert delivery["generation"] == observation.generation
    assert delivery["status"] == "completed"
    assert (
        activity_publisher.publish.await_args.args[0].status is OperationalActivityStatus.COMPLETED
    )


async def test_ontology_observer_retries_configuration_event_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        observer,
        recovery,
        observation_journal,
        _ontology_store,
        _history_store,
        projector,
        activity_publisher,
        release_digest,
    ) = _ontology_observer_harness(monkeypatch)
    activity_publisher.configuration_event_publisher.side_effect = RuntimeError(
        "broker unavailable"
    )

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await observer(_promoted_observation("snapshot-event-failure"))

    activity = activity_publisher.publish.await_args.args[0]
    assert activity.status is OperationalActivityStatus.FAILED
    assert activity.reason_codes == ("configuration_event_publish_failed",)
    store = projector.construction_kwargs["status_store"]
    manifest = {
        "generation": "snapshot-event-failure",
        "ontology_release_digest": release_digest,
        "manifest_digest": "sha256:" + "1" * 64,
        "complete": True,
    }
    await store.write_state("inventory-ontology:manifest", manifest)
    await store.write_state("inventory-ontology:status", {**manifest, "status": "available"})
    observation_journal.load_pending_promoted_snapshot.side_effect = [
        _promoted_observation("snapshot-event-failure"),
        None,
    ]
    activity_publisher.configuration_event_publisher.side_effect = None

    await recovery()

    assert activity_publisher.configuration_event_publisher.await_count == 2
    assert projector.apply.await_count == 1
    delivery = await store.read_state("inventory-configuration:delivery")
    assert delivery["status"] == "completed"


async def test_ontology_observer_delivers_objects_with_classified_relationship_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai.shared.providers.inventory import (
        RelationshipDrop,
        RelationshipDropReason,
        RelationshipUnavailableReason,
    )

    observer, _, _, _, history, projector, publisher, _ = _ontology_observer_harness(monkeypatch)
    observation = _promoted_observation("snapshot-gap")
    observation = PromotedInventoryObservation(
        generation=observation.generation,
        resources=observation.resources,
        links=(),
        complete=True,
        recorded_at=observation.recorded_at,
        relationship_drops=(
            RelationshipDrop(
                reason=RelationshipDropReason.MISSING_TARGET_ENDPOINT,
                unavailable_reason=RelationshipUnavailableReason.TARGET_OUTSIDE_ACTIVE_GENERATION,
            ),
        ),
    )

    await observer(observation)

    projector.apply.assert_awaited_once()
    history.append.assert_not_awaited()
    publisher.configuration_event_publisher.assert_awaited_once_with(observation)
    assert publisher.publish.await_args.args[0].status is OperationalActivityStatus.DEGRADED


async def test_ontology_observer_does_not_advance_projection_after_history_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        observer,
        _recovery,
        _observation_journal,
        ontology_store,
        history_store,
        projector,
        activity_publisher,
        _release_digest,
    ) = _ontology_observer_harness(monkeypatch)
    history_store.append.side_effect = RuntimeError("history unavailable")

    with pytest.raises(RuntimeError, match="history unavailable"):
        await observer(_promoted_observation("snapshot-history-failure"))

    ontology_store.sync_catalog.assert_awaited_once()
    projector.apply.assert_not_awaited()
    activity = activity_publisher.publish.await_args.args[0]
    assert activity.reason_codes == ("topology_history_failed",)


async def test_ontology_observer_retains_history_before_projection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        observer,
        _recovery,
        _observation_journal,
        _ontology_store,
        history_store,
        projector,
        activity_publisher,
        _release_digest,
    ) = _ontology_observer_harness(monkeypatch)
    projector.apply.side_effect = RuntimeError("projection unavailable")

    with pytest.raises(RuntimeError, match="projection unavailable"):
        await observer(_promoted_observation("snapshot-projection-failure"))

    history_store.append.assert_awaited_once()
    activity = activity_publisher.publish.await_args.args[0]
    assert activity.reason_codes == ("projection_failed",)


async def test_ontology_recovery_replays_pending_history_before_new_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_store = _state_store_double()
    monkeypatch.setattr(
        "fdai.delivery.inventory_ontology_observer.PostgresStateStore",
        lambda **_: status_store,
    )
    (
        observer,
        recovery,
        observation_journal,
        _ontology_store,
        history_store,
        projector,
        _activity_publisher,
        _release_digest,
    ) = _ontology_observer_harness(monkeypatch)
    observation = _promoted_observation("snapshot-recovery")
    history_store.append.side_effect = [RuntimeError("history unavailable"), None]

    with pytest.raises(RuntimeError, match="history unavailable"):
        await observer(observation)

    observation_journal.load_pending_promoted_snapshot.side_effect = [observation, None]
    status_store = projector.construction_kwargs["status_store"]
    await status_store.write_state(
        "inventory-ontology:manifest",
        {
            "generation": observation.generation,
            "ontology_release_digest": _release_digest,
            "complete": True,
            "manifest_digest": "sha256:" + "c" * 64,
        },
    )
    await recovery()

    assert observation_journal.load_pending_promoted_snapshot.await_count == 2
    from fdai.delivery.inventory_configuration_events import configuration_delivery_key

    delivery_key = configuration_delivery_key(observation.generation)
    assert [call.args[0] for call in status_store.read_state.await_args_list] == [
        "inventory-ontology:manifest",
        "inventory-ontology:manifest",
        "inventory-ontology:status",
        delivery_key,
        delivery_key,
        delivery_key,
        "inventory-configuration:delivery",
        "inventory-ontology:manifest",
    ]
    assert history_store.append.await_count == 2
    projector.apply.assert_awaited_once()


async def test_ontology_observer_keeps_incomplete_projection_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        observer,
        _recovery,
        _observation_journal,
        _ontology_store,
        _history_store,
        projector,
        activity_publisher,
        _release_digest,
    ) = _ontology_observer_harness(monkeypatch)
    projector.apply.return_value = SimpleNamespace(
        status=InventoryOntologyProjectionStatus.UNAVAILABLE,
        object_count=0,
        link_count=0,
        complete=False,
        dropped_reasons=("unmapped_resource_type",),
    )

    with pytest.raises(RuntimeError, match="projection is incomplete"):
        await observer(_promoted_observation("snapshot-incomplete"))

    activity_publisher.configuration_event_publisher.assert_not_awaited()
    activity = activity_publisher.publish.await_args.args[0]
    assert activity.status.value == "degraded"


@pytest.mark.parametrize(
    "defect", ["missing", "generation", "release", "incomplete", "digest", "pending"]
)
async def test_recovery_rejects_unverified_completion(defect: str) -> None:
    from fdai.delivery.inventory_sync_cli_support import recover_ontology_projection

    observation = _promoted_observation("snapshot-recovery")
    manifest: dict[str, object] = {
        "generation": observation.generation,
        "ontology_release_digest": "sha256:" + "a" * 64,
        "complete": True,
        "manifest_digest": "sha256:" + "c" * 64,
    }
    changes = {
        "generation": "generation",
        "release": "ontology_release_digest",
        "incomplete": "complete",
        "digest": "manifest_digest",
    }
    if defect in changes:
        manifest[changes[defect]] = False if defect == "incomplete" else "invalid"
    load_pending = AsyncMock(
        side_effect=[observation, observation if defect == "pending" else None]
    )
    observe = AsyncMock()
    store = SimpleNamespace(
        read_state=AsyncMock(return_value=None if defect == "missing" else manifest)
    )
    with pytest.raises(
        RuntimeError,
        match="deployment alignment" if defect == "release" else "readback did not converge",
    ):
        await recover_ontology_projection(
            load_pending=load_pending,
            observe=observe,
            status_store=store,
            release_digest="sha256:" + "a" * 64,
        )
    if defect == "release":
        observe.assert_not_awaited()
    else:
        observe.assert_awaited_once_with(observation)


async def test_operator_requested_recovery_skips_release_mismatched_pending() -> None:
    from fdai.delivery.inventory_sync_cli_support import recover_ontology_projection

    observation = _promoted_observation("snapshot-recovery")
    observe = AsyncMock()
    await recover_ontology_projection(
        load_pending=AsyncMock(return_value=observation),
        observe=observe,
        status_store=SimpleNamespace(
            read_state=AsyncMock(return_value={"ontology_release_digest": "sha256:" + "b" * 64})
        ),
        release_digest="sha256:" + "a" * 64,
        allow_release_mismatch_collection=True,
    )

    observe.assert_not_awaited()


async def test_ontology_observer_forwards_operator_requested_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recover = AsyncMock()
    monkeypatch.setattr(
        "fdai.delivery.inventory_ontology_observer.inventory_sync_cli_support.recover_ontology_projection",
        recover,
    )
    recovery = _ontology_observer_harness(monkeypatch, operator_requested=True)[1]

    await recovery()

    assert recover.await_args.kwargs["allow_release_mismatch_collection"] is True


async def test_recovery_deadline_cancels_before_new_collection() -> None:
    from fdai.delivery.inventory_sync_cli_support import recover_ontology_projection

    load_pending = AsyncMock(side_effect=[_promoted_observation("snapshot-recovery")])
    stopped = asyncio.Event()

    async def observe(_observation: PromotedInventoryObservation) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    with pytest.raises(TimeoutError):
        await recover_ontology_projection(
            load_pending=load_pending,
            observe=observe,
            status_store=None,
            release_digest="sha256:" + "a" * 64,
            timeout_seconds=0.01,
        )
    assert stopped.is_set()


async def test_recovery_no_pending_generation_performs_no_writes() -> None:
    from fdai.delivery.inventory_sync_cli_support import recover_ontology_projection

    observe = AsyncMock()
    store = SimpleNamespace(read_state=AsyncMock())
    await recover_ontology_projection(
        load_pending=AsyncMock(return_value=None),
        observe=observe,
        status_store=store,
        release_digest="sha256:" + "a" * 64,
    )
    observe.assert_not_awaited()
    store.read_state.assert_not_awaited()


async def test_ontology_recovery_allows_fresh_collection_after_degraded_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "fdai.delivery.inventory_ontology_observer.PostgresStateStore",
        lambda **_: _state_store_double(),
    )
    (
        _observer,
        recovery,
        observation_journal,
        _ontology_store,
        _history_store,
        projector,
        activity_publisher,
        _release_digest,
    ) = _ontology_observer_harness(monkeypatch)
    observation_journal.load_pending_promoted_snapshot.return_value = _promoted_observation(
        "snapshot-incomplete-recovery"
    )
    projector.apply.return_value = SimpleNamespace(
        status=InventoryOntologyProjectionStatus.UNAVAILABLE,
        object_count=0,
        link_count=0,
        complete=False,
        dropped_reasons=("unmapped_resource_type",),
    )

    await recovery()

    observation_journal.load_pending_promoted_snapshot.assert_awaited_once()
    activity = activity_publisher.publish.await_args.args[0]
    assert activity.status.value == "degraded"


async def test_recovery_delta_forwards_every_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "FDAI_INVENTORY_SCOPES": (
                "00000000-0000-0000-0000-000000000001,00000000-0000-0000-0000-000000000002"
            ),
            "FDAI_INVENTORY_RECOVERY_DELTA": "1",
        }
    )
    forward = AsyncMock(side_effect=(2, 3))
    state_store = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(
        "fdai.delivery.inventory_change_acceleration.forward_inventory_delta",
        forward,
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_change_acceleration.PostgresStateStore",
        lambda **_: state_store,
    )
    identity = StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="test-token",  # noqa: S106 - deterministic test credential
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(_http_ok)) as client:
        locked_scopes: list[str] = []

        class ScopeLock:
            @asynccontextmanager
            async def acquire(self, resource_id: str) -> AsyncIterator[None]:
                locked_scopes.append(resource_id)
                yield

        published = await _forward_recovery_deltas(
            config=config,
            identity=identity,
            vocabulary=_vocabulary(),
            http_client=client,
            event_bus=InMemoryEventBus(),
            topic="events",
            scope_lock=ScopeLock(),
        )

    assert published == 5
    assert [call.kwargs["scope"] for call in forward.await_args_list] == list(config.scopes)
    assert all(call.kwargs["properties_complete"] is False for call in forward.await_args_list)
    assert locked_scopes == [f"inventory-recovery-delta:{scope}" for scope in config.scopes]
    state_store.aclose.assert_awaited_once_with()


def test_container_entrypoint_translates_positional_modes() -> None:
    assert container_argv(["once"]) == []
    assert container_argv(["loop"]) == ["--loop"]
    with pytest.raises(ValueError, match="accepts once or loop"):
        container_argv([])
