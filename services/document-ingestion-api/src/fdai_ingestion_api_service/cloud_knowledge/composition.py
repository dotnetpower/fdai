"""Bind approved source collection and offline intake without selecting ambient trust."""

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime

from fdai_ingestion_api_service.cloud_knowledge.collector import CloudDocumentCollector
from fdai_ingestion_api_service.cloud_knowledge.policy import policy_reader
from fdai_ingestion_api_service.cloud_knowledge.scheduler import CloudKnowledgeScheduler
from fdai_ingestion_api_service.cloud_knowledge.service import CloudKnowledgeService
from fdai_ingestion_api_service.cloud_knowledge.store import PostgresCloudKnowledgeStore
from fdai_ingestion_api_service.cloud_knowledge.transport import PublicDocumentationTransport
from fdai_ingestion_api_service.ingestion import DocumentIngestionService


def bind_cloud_knowledge(
    env: Mapping[str, str], *, ingestion: DocumentIngestionService, dsn: str
) -> CloudKnowledgeService | None:
    """Missing independent policies means unavailable, never fixture or test-key fallback."""
    registry_path = env.get("FDAI_CLOUD_KNOWLEDGE_REGISTRY_PATH", "").strip()
    trust_path = env.get("FDAI_CLOUD_KNOWLEDGE_TRUST_PATH", "").strip()
    if not registry_path and not trust_path:
        return None
    if not registry_path or not trust_path:
        raise ValueError("cloud knowledge requires both independently approved policies")
    read = policy_reader(env)
    registry, trust = read()
    output_format = env.get("FDAI_CLOUD_KNOWLEDGE_FORMAT", "v2")
    if output_format not in {"v2", "v3"}:
        raise ValueError("cloud knowledge format must be v2 or v3")
    allowed = set(env.get("FDAI_DOCUMENT_COLLECTIONS", "shared-knowledge").split(","))
    if any(source.collection_id not in allowed for source in registry.sources):
        raise ValueError("cloud sources MUST belong to configured document collections")

    def clock() -> datetime:
        return datetime.now(tz=UTC)

    store = PostgresCloudKnowledgeStore(dsn=dsn)
    scheduler = CloudKnowledgeScheduler(
        registry=registry,
        store=store,
        collector=CloudDocumentCollector(
            PublicDocumentationTransport(), collector_id="Huginn", structured=output_format == "v3"
        ),
        clock=clock,
    )
    return CloudKnowledgeService(
        registry=registry,
        trust=trust,
        store=store,
        scheduler=scheduler,
        ingestion=ingestion,
        clock=clock,
        reader_groups=(env["FDAI_RBAC_READERS_GROUP_ID"],),
        retention_policy=env.get("FDAI_DOCUMENT_POLICY_VERSION", "prod-policy-v1"),
        current_policy=read,
        structured=output_format == "v3",
    )


async def scheduled_cloud_checks(service: CloudKnowledgeService) -> None:
    """Wake the existing API host daily; each bounded sweep respects source-specific due times."""
    while True:
        try:
            await service.refresh()
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "cloud_knowledge_sweep_failed:%s", type(exc).__name__
            )
        await asyncio.sleep(86400)
