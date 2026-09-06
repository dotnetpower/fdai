"""Inventory job configuration boundary tests."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import yaml
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.inventory import AzureResourceGraphInventory
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.inventory_change_acceleration import (
    forward_recovery_deltas as _forward_recovery_deltas,
)
from fdai.delivery.inventory_job_config import InventoryJobConfig, verify_declarative_sha256
from fdai.delivery.inventory_scheduler import (
    CollectionScheduleAction,
    CollectionScheduleDecision,
    ProviderPressure,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.inventory_sync_cli import (
    _build_kubernetes_enricher,
    _build_ontology_observer,
    _build_sources,
    _collect_kubernetes_lifecycle,
    _drain_change_stream,
    _load_relationship_mapping_catalog,
    _main,
    _publish_collection_health,
    _resolve_resource_types,
    _run_due_once,
    _workload_identity,
    container_argv,
    run,
)
from fdai.delivery.kubernetes_api_inventory import KubernetesApiInventoryConfig
from fdai.delivery.kubernetes_inventory import UnavailableKubernetesInventoryEnricher
from fdai.delivery.operational_activity import EventBusOperationalActivityPublisher
from fdai.delivery.persistence.postgres_inventory_reconciliation import (
    InventoryReconciliationHealthState,
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

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _vocabulary() -> ResourceTypeRegistry:
    path = _REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
    return load_resource_type_registry_from_mapping(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )


def _ontology_observer_harness(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
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
        "fdai.delivery.inventory_sync_cli.load_ontology_catalog",
        lambda *a, **k: catalog,
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.PostgresOntologyInstanceStore",
        lambda **_: ontology_store,
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.PostgresTopologyHistoryStore",
        lambda **_: history_store,
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.InventoryOntologyProjector",
        lambda **kwargs: projector.construction_kwargs.update(kwargs) or projector,
    )
    observation_journal = SimpleNamespace(
        append_promoted_snapshot=AsyncMock(
            return_value=SimpleNamespace(
                journal_high_watermark=7,
                projection_high_watermark=7,
            )
        ),
        mark_ontology_projected=AsyncMock(),
        load_pending_promoted_snapshot=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.build_observation_journal",
        lambda *_args, **_kwargs: observation_journal,
    )
    activity_publisher = SimpleNamespace(publish=AsyncMock())
    observer, recovery = _build_ontology_observer(
        config,
        vocabulary=_vocabulary(),
        publisher=cast(EventBusOperationalActivityPublisher, activity_publisher),
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
    assert config.snapshot_policy("arg").max_requests_per_window == 180
    assert config.collection_policy is not None


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


def test_job_loads_reviewed_kubernetes_relationship_mappings() -> None:
    catalog = _load_relationship_mapping_catalog()

    assert {
        mapping.mapping_id for mapping in catalog.mappings if mapping.provider == "kubernetes"
    } == {
        "kubernetes.agent-pool-contains-node",
        "kubernetes.cluster-contains-ingress-class",
        "kubernetes.cluster-contains-namespace",
        "kubernetes.endpoint-slice-exposed-by-service",
        "kubernetes.ingress-attached-to-class",
        "kubernetes.ingress-routes-to-service",
        "kubernetes.namespace-contains-resource",
        "kubernetes.node-backed-by-vmss-vm",
        "kubernetes.pod-scheduled-on-node",
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
            "FDAI_KUBERNETES_CLUSTER_REF": "cluster-ref-example",
            "FDAI_KUBERNETES_TOKEN_PATH": "/var/run/secrets/kubernetes/token",
            "FDAI_KUBERNETES_CA_PATH": "/var/run/secrets/kubernetes/ca.crt",
        }
    )

    assert config.kubernetes_api_server == "https://kubernetes.example"
    assert config.kubernetes_cluster_ref == "cluster-ref-example"
    assert config.kubernetes_token_path == Path("/var/run/secrets/kubernetes/token")
    assert config.kubernetes_ca_path == Path("/var/run/secrets/kubernetes/ca.crt")
    assert config.kubernetes_auth_mode == "service-account"


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
            "FDAI_KUBERNETES_CLUSTER_REF": "cluster-ref-example",
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
        cluster_ref="cluster-ref-example",
    )
    assert source_kwargs["auth"].token_path == Path("/var/run/secrets/kubernetes/token")
    assert source_kwargs["http_client"] is fake_http_client
    enricher_factory.assert_called_once_with(
        source=source_factory.return_value,
        relationship_mapping_catalog=catalog,
    )


def test_job_config_accepts_workload_identity_kubernetes_binding() -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
            "FDAI_KUBERNETES_API_SERVER": "https://kubernetes.example",
            "FDAI_KUBERNETES_CLUSTER_REF": "cluster-ref-example",
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

    assert await _drain_change_stream(config) is None


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

    assert await _drain_change_stream(config) == 0
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

    assert await _drain_change_stream(config) == 8


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

    assert await _drain_change_stream(config) == 5


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

    assert await _drain_change_stream(config) == 0
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
    runtime_settings = SimpleNamespace(effective_values=AsyncMock(return_value={}))
    printed = Mock()
    monkeypatch.setattr(
        "fdai.delivery.runtime_settings.runtime_settings_service_from_env",
        lambda _: runtime_settings,
    )
    monkeypatch.setattr(InventoryJobConfig, "from_env", lambda **_: config)
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli._drain_change_stream",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "fdai.delivery.inventory_sync_cli.PostgresInventoryReconciliationGate",
        lambda **_: AsyncMock(return_value=False),
    )
    monkeypatch.setattr("builtins.print", printed)

    assert await _run_due_once() is config
    printed.assert_called_once_with(
        "inventory reconciliation not due; change records published 0",
        flush=True,
    )


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


async def test_collection_health_persists_only_sanitized_aggregate_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )
    store = SimpleNamespace(write_state=AsyncMock())
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

    observation_journal.load_pending_promoted_snapshot.return_value = observation
    await recovery()

    observation_journal.load_pending_promoted_snapshot.assert_awaited_once()
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
    monkeypatch.setattr(
        "fdai.delivery.inventory_change_acceleration.forward_inventory_delta",
        forward,
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
    assert locked_scopes == [f"inventory-recovery-delta:{scope}" for scope in config.scopes]


def test_container_entrypoint_translates_positional_modes() -> None:
    assert container_argv(["once"]) == []
    assert container_argv(["loop"]) == ["--loop"]
    with pytest.raises(ValueError, match="accepts once or loop"):
        container_argv([])
