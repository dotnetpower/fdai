"""Inventory job configuration boundary tests."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import yaml
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.inventory_sync_cli import (
    InventoryJobConfig,
    _build_ontology_observer,
    _build_sources,
    _forward_recovery_deltas,
    _resolve_resource_types,
    _verify_sha256,
)
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.runtime.inventory_ontology import InventoryOntologyProjectionStatus
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _vocabulary():
    path = _REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
    return load_resource_type_registry_from_mapping(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )


def _ontology_observer_harness(monkeypatch: pytest.MonkeyPatch):
    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://example",
            "AZURE_SUBSCRIPTION_ID": "sub-1",
        }
    )
    ontology_store = SimpleNamespace(sync_catalog=AsyncMock())
    history_store = SimpleNamespace(append=AsyncMock())
    projector = SimpleNamespace(
        apply=AsyncMock(
            return_value=SimpleNamespace(
                status=InventoryOntologyProjectionStatus.AVAILABLE,
                object_count=1,
                link_count=0,
                dropped_reasons=(),
            )
        )
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
        lambda **_: projector,
    )
    activity_publisher = SimpleNamespace(publish=AsyncMock())
    observer = _build_ontology_observer(
        config,
        vocabulary=_vocabulary(),
        publisher=activity_publisher,
        evidence_counts={},
    )
    return (
        observer,
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


def test_job_config_rejects_unsigned_declarative_fallback() -> None:
    with pytest.raises(ValueError, match="requires"):
        InventoryJobConfig.from_env(
            {
                "FDAI_INVENTORY_DSN": "postgresql://example",
                "AZURE_SUBSCRIPTION_ID": "sub-1",
                "FDAI_INVENTORY_SOURCES": "arg,declarative",
            }
        )


def test_declarative_sha_verification(tmp_path) -> None:
    fixture = tmp_path / "inventory.yaml"
    fixture.write_text("resources: []\nlinks: []\n", encoding="utf-8")
    digest = hashlib.sha256(fixture.read_bytes()).hexdigest()

    _verify_sha256(fixture, digest)
    with pytest.raises(ValueError, match="does not match"):
        _verify_sha256(fixture, "0" * 64)


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
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: None)) as client:
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
    )
    assert sources[1].manifest.metadata["link_types"] == ("contains",)


async def test_ontology_observer_publishes_durable_topology_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        observer,
        ontology_store,
        history_store,
        projector,
        _activity_publisher,
        release_digest,
    ) = _ontology_observer_harness(monkeypatch)

    await observer(_promoted_observation("snapshot-1"))

    history_store.append.assert_awaited_once()
    assert history_store.append.await_args.kwargs["ontology_release_digest"] == release_digest
    ontology_store.sync_catalog.assert_awaited_once()
    projector.apply.assert_awaited_once()


async def test_ontology_observer_attempts_projection_after_history_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        observer,
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
    projector.apply.assert_awaited_once()
    activity = activity_publisher.publish.await_args.args[0]
    assert activity.reason_codes == ("topology_history_failed",)


async def test_ontology_observer_retains_history_before_projection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        observer,
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
    monkeypatch.setattr("fdai.delivery.inventory_sync_cli.forward_inventory_delta", forward)
    identity = StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="test-token",  # noqa: S106 - deterministic test credential
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: None)) as client:
        locked_scopes: list[str] = []

        class ScopeLock:
            @asynccontextmanager
            async def acquire(self, resource_id: str):
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
