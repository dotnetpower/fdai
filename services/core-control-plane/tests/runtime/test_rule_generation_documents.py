"""Production Rule generation document snapshot tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.agents import PantheonRuntime
from fdai.delivery.catalog_search import InMemoryCatalogSemanticIndex
from fdai.rule_catalog.schema.catalog_search import (
    catalog_search_schema_digest,
    rule_reference_catalog_digest,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RuleGenerationBuildRequestEvent,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import RuleCorpus
from fdai.runtime.bootstrap_lifecycle import publish_rule_generation_reconciliation
from fdai.runtime.rule_generation_documents import (
    RuleGenerationDocumentsUnavailableError,
    build_rule_generation_document_resolver,
    build_rule_generation_reconciliation,
    get_or_create_rule_generation_request,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[4]
CATALOG_ROOT = REPO_ROOT / "rule-catalog"


class _Embedding:
    dim = 384
    embedding_space_id = "model-binding:test:sha256:" + "a" * 64
    embedding_model_version = "2026-08-01"

    async def embed(self, text: str) -> tuple[float, ...]:
        del text
        return (0.0,) * self.dim


class _FailOnceEventBus(InMemoryEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.publish_attempts = 0

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        self.publish_attempts += 1
        if self.publish_attempts == 1:
            raise RuntimeError("synthetic broker failure")
        return await super().publish(topic, key, payload)


def _catalogs():  # type: ignore[no-untyped-def]
    registry = PackageResourceSchemaRegistry()
    ontology = load_ontology_catalog(
        CATALOG_ROOT,
        schema_registry=registry,
        probes_root=CATALOG_ROOT / "probes",
    )
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (CATALOG_ROOT / "vocabulary/resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    rules = load_rule_catalog(
        CATALOG_ROOT / "catalog",
        schema_registry=registry,
        action_types=ontology.action_types,
        resource_types=resource_types,
        policies_root=REPO_ROOT / "policies",
        remediation_root=CATALOG_ROOT / "remediation",
    )
    return ontology, rules


async def test_resolver_builds_exact_active_snapshot_from_governed_catalogs() -> None:
    ontology, rules = _catalogs()
    release = ontology.build_release()
    resolver = build_rule_generation_document_resolver(
        catalog_root=CATALOG_ROOT,
        rules=rules,
        action_types=ontology.action_types,
        ontology_release=release,
        embedder=_Embedding(),
    )
    request = RuleGenerationBuildRequestEvent.create(
        correlation_id="startup-catalog-snapshot",
        corpus=RuleCorpus.ACTIVE,
        catalog_digest=rule_reference_catalog_digest(rules),
        semantic_schema_digest=catalog_search_schema_digest(),
        ontology_release_digest=release.digest,
        embedding_space_id=_Embedding.embedding_space_id,
        embedding_model_version=_Embedding.embedding_model_version,
        embedding_dimension=_Embedding.dim,
        requested_at=datetime(2026, 8, 13, tzinfo=UTC),
    )

    documents = await resolver.resolve(request)

    assert len(documents) == len(rules)
    assert {document.rule_id for document in documents} == {rule.id for rule in rules}
    assert all(document.manifest_digest is not None for document in documents)


async def test_reconciliation_request_reuses_exact_durable_timestamp_on_restart() -> None:
    ontology, rules = _catalogs()
    resolver = build_rule_generation_document_resolver(
        catalog_root=CATALOG_ROOT,
        rules=rules,
        action_types=ontology.action_types,
        ontology_release=ontology.build_release(),
        embedder=_Embedding(),
    )
    store = InMemoryStateStore()

    first = await get_or_create_rule_generation_request(
        resolver=resolver,
        store=store,
        requested_at=datetime(2026, 8, 13, tzinfo=UTC),
    )
    restarted = await get_or_create_rule_generation_request(
        resolver=resolver,
        store=store,
        requested_at=datetime(2026, 8, 14, tzinfo=UTC),
    )

    assert restarted == first
    assert restarted.request_digest == first.request_digest
    assert await store.verify_chain()

    changed = type(resolver)(
        active_documents=(
            replace(
                resolver.active_documents[0],
                text=resolver.active_documents[0].text + " changed",
            ),
            *resolver.active_documents[1:],
        ),
        discovery_documents=resolver.discovery_documents,
        catalog_digest=resolver.catalog_digest,
        semantic_schema_digest=resolver.semantic_schema_digest,
        ontology_release_digest=resolver.ontology_release_digest,
        embedding_space_id=resolver.embedding_space_id,
        embedding_model_version=resolver.embedding_model_version,
        embedding_dimension=resolver.embedding_dimension,
    )
    changed_request = await get_or_create_rule_generation_request(
        resolver=changed,
        store=store,
        requested_at=datetime(2026, 8, 14, tzinfo=UTC),
    )
    assert changed_request.generation_request_id != first.generation_request_id


async def test_production_reconciliation_skips_request_for_exact_active_generation() -> None:
    ontology, rules = _catalogs()
    reconciliation = await build_rule_generation_reconciliation(
        catalog_root=CATALOG_ROOT,
        rules=rules,
        action_types=ontology.action_types,
        ontology_release=ontology.build_release(),
        embedder=_Embedding(),
        index=InMemoryCatalogSemanticIndex(),
        store=InMemoryStateStore(),
        request_generation=False,
        requested_at=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert reconciliation.request is None
    assert reconciliation.workers.build is not None
    assert reconciliation.workers.validation is not None


async def test_reconciliation_publish_retries_exact_request_after_broker_failure() -> None:
    ontology, rules = _catalogs()
    reconciliation = await build_rule_generation_reconciliation(
        catalog_root=CATALOG_ROOT,
        rules=rules,
        action_types=ontology.action_types,
        ontology_release=ontology.build_release(),
        embedder=_Embedding(),
        index=InMemoryCatalogSemanticIndex(),
        store=InMemoryStateStore(),
        request_generation=True,
        requested_at=datetime(2026, 8, 13, tzinfo=UTC),
    )
    assert reconciliation.request is not None
    event_bus = _FailOnceEventBus()
    runtime = PantheonRuntime.build(provider=event_bus, raw_event_topic="fdai.events")

    await publish_rule_generation_reconciliation(
        runtime=runtime,
        request=reconciliation.request,
        stop=asyncio.Event(),
        retry_interval_seconds=0.001,
    )

    assert event_bus.publish_attempts == 2


def test_resolver_rejects_embedder_without_governed_identity_before_catalog_io() -> None:
    ontology, rules = _catalogs()
    embedder = _Embedding()
    embedder.embedding_space_id = ""

    with pytest.raises(RuleGenerationDocumentsUnavailableError, match="embedding_space_id"):
        build_rule_generation_document_resolver(
            catalog_root=Path("missing"),
            rules=rules,
            action_types=ontology.action_types,
            ontology_release=ontology.build_release(),
            embedder=embedder,
        )
