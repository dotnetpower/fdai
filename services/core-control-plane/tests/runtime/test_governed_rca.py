from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import psycopg
import pytest
from fdai.composition import default_container
from fdai.core.rca.governed_knowledge_evidence import (
    GovernedKnowledgeEvidenceGatherer,
)
from fdai.delivery.governed_rca_context import (
    GovernedRcaContextConfig,
    RuntimeGovernedRcaContextProvider,
)
from fdai.delivery.persistence.postgres_governed_document_read import (
    PostgresGovernedDocumentReadConfig,
    PostgresGovernedDocumentReadStore,
)
from fdai.runtime.governed_rca import bind_governed_rca_from_environment
from fdai.shared.config import AppConfig
from fdai.shared.contracts import DocumentVersion
from fdai.shared.providers.document_ingestion import DocumentAccessDeniedError

AT = datetime(2026, 9, 5, tzinfo=UTC)
RELEASE = f"sha256:{'a' * 64}"


def _environment() -> dict[str, str]:
    return {
        "FDAI_RCA_DOCUMENT_DSN": "postgresql://localhost/fdai",
        "FDAI_RCA_GOVERNED_COLLECTION_ID": "operations",
        "FDAI_RCA_GOVERNED_ACCESS_REFS_JSON": '["collection:operations"]',
        "FDAI_RCA_GOVERNED_ACTOR_GROUPS_JSON": '["group:responders"]',
    }


def test_context_config_is_disabled_only_when_every_binding_is_absent() -> None:
    assert GovernedRcaContextConfig.from_environ({}) is None
    with pytest.raises(ValueError, match="MUST be bound together"):
        GovernedRcaContextConfig.from_environ({"FDAI_RCA_GOVERNED_COLLECTION_ID": "operations"})
    with pytest.raises(ValueError, match="bounded"):
        GovernedRcaContextConfig(
            collection_id="operations",
            allowed_access_refs=frozenset({"x" * 513}),
            actor_groups=frozenset({"group:responders"}),
        )


@pytest.mark.asyncio
async def test_context_provider_binds_system_principal_incident_scope_and_cutoff() -> None:
    config = GovernedRcaContextConfig.from_environ(_environment())
    assert config is not None
    context = await RuntimeGovernedRcaContextProvider(config=config).context_for(
        incident_ref="incident:example",
        resource_ref="resource:example",
        cutoff=AT,
        ontology_release_digest=RELEASE,
        catalog_revision="catalog-r1",
    )

    assert context.authenticated_context.principal_ref == "principal:fdai-rca"
    assert context.authenticated_context.purpose == "incident-review"
    assert context.read_request.scope == ("incident:example", "resource:example")
    assert context.read_request.cutoff == AT
    assert context.access_context.collection_id == "operations"
    assert context.access_context.allowed_access_refs == frozenset({"collection:operations"})


def test_runtime_binds_gatherer_and_context_as_one_pair(app_config: AppConfig) -> None:
    container = bind_governed_rca_from_environment(
        default_container(app_config),
        environment=_environment(),
    )

    assert isinstance(
        container.governed_knowledge.gatherer,
        GovernedKnowledgeEvidenceGatherer,
    )
    assert isinstance(
        container.governed_knowledge.context_provider,
        RuntimeGovernedRcaContextProvider,
    )


@pytest.mark.asyncio
async def test_read_store_requires_exact_reader_group() -> None:
    store = PostgresGovernedDocumentReadStore(
        config=PostgresGovernedDocumentReadConfig(dsn="postgresql://localhost/fdai")
    )
    version = cast(
        DocumentVersion,
        SimpleNamespace(
            uploader_id="principal:author",
            access=SimpleNamespace(reader_groups=("group:responders",)),
        ),
    )

    await store.authorize_read(
        actor_id="principal:fdai-rca",
        actor_groups=frozenset({"group:responders"}),
        version=version,
    )
    with pytest.raises(DocumentAccessDeniedError):
        await store.authorize_read(
            actor_id="principal:fdai-rca",
            actor_groups=frozenset({"group:other"}),
            version=version,
        )


async def test_governed_document_connection_ignores_process_role_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    async def connect(dsn: str, **kwargs: object) -> object:
        captured["dsn"] = dsn
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    store = PostgresGovernedDocumentReadStore(
        config=PostgresGovernedDocumentReadConfig(dsn="postgresql://reader@example/fdai")
    )

    assert await store._connect() is sentinel  # type: ignore[comparison-overlap]  # noqa: SLF001
    assert captured["options"] == ""
