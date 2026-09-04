"""Runtime composition for principal-scoped governed RCA document evidence."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from fdai.composition import Container
from fdai.core.rca.governed_document_evidence import GovernedDocumentEvidenceReadAdapter
from fdai.core.rca.governed_knowledge_evidence import (
    GovernedKnowledgeBindings,
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
from fdai.shared.providers.document_ingestion import (
    DocumentAccessProvider,
    DocumentMetadataStore,
    DocumentSearch,
)

_LOGGER = logging.getLogger("fdai.startup")


def bind_governed_rca_from_environment(
    container: Container,
    *,
    environment: Mapping[str, str],
) -> Container:
    """Bind read-only governed documents only when the complete context is configured."""

    if container.governed_knowledge is not None:
        return container
    context_config = GovernedRcaContextConfig.from_environ(environment)
    if context_config is None:
        _LOGGER.info(
            "governed_rca_unavailable",
            extra={"reason": "collection_access_context_absent"},
        )
        return container
    dsn = environment.get("FDAI_RCA_DOCUMENT_DSN", "").strip()
    if not dsn:
        raise ValueError(
            "FDAI_RCA_DOCUMENT_DSN is required when governed RCA context is configured"
        )
    freshness_seconds = _bounded_integer(
        environment.get("FDAI_RCA_DOCUMENT_FRESHNESS_SECONDS", ""),
        default=86_400,
        minimum=60,
        maximum=604_800,
        name="FDAI_RCA_DOCUMENT_FRESHNESS_SECONDS",
    )
    store = PostgresGovernedDocumentReadStore(
        config=PostgresGovernedDocumentReadConfig(
            dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        )
    )
    reader = GovernedDocumentEvidenceReadAdapter(
        search=cast(DocumentSearch, store),
        metadata=cast(DocumentMetadataStore, store),
        access=cast(DocumentAccessProvider, store),
        clock=lambda: datetime.now(tz=UTC),
        freshness_ceiling_seconds=freshness_seconds,
    )
    _LOGGER.info("governed_rca_ready")
    return replace(
        container,
        governed_knowledge=GovernedKnowledgeBindings(
            gatherer=GovernedKnowledgeEvidenceGatherer(reader=reader),
            context_provider=RuntimeGovernedRcaContextProvider(config=context_config),
        ),
    )


def _bounded_integer(
    raw: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
    name: str,
) -> int:
    if not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} MUST be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} MUST be in [{minimum}, {maximum}]")
    return value


__all__ = ["bind_governed_rca_from_environment"]
