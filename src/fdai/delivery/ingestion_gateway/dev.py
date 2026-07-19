"""Explicit local composition for the dedicated document-ingestion gateway."""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

from starlette.applications import Starlette

from fdai.core.document_ingestion import DocumentIngestionService, DocumentIngestionWorker
from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.core.stewardship.handover_bootstrap import HandoverBootstrapper
from fdai.core.tiers.t1_lightweight.testing import DeterministicEmbeddingModel
from fdai.delivery.document_index import InMemoryEmbeddingDocumentIndex
from fdai.delivery.ingestion_gateway.handover import (
    HandoverBootstrapConsumer,
    InMemoryHandoverDraftStore,
)
from fdai.delivery.ingestion_gateway.main import IngestionGatewayConfig, build_app
from fdai.delivery.read_api.auth import UnsafeClaimsExtractor, build_authenticator
from fdai.shared.contracts import IngestionCapabilities, SourceStorageMode
from fdai.shared.providers.local.document_ingestion import (
    SignatureProtectionInspector,
    StandardLibraryDocumentExtractor,
)
from fdai.shared.providers.testing.document_ingestion import (
    InMemoryDocumentAccessProvider,
    InMemoryDocumentArtifactStore,
    InMemoryDocumentMetadataStore,
    InMemoryDocumentObjectStore,
    RecordingDocumentActivitySink,
    StaticMalwareScanner,
)

_LOCAL_COLLECTION = "shared-knowledge"
_LOCAL_ACTOR = "ingestion-dev"
_CORS_ORIGINS_ENV = "FDAI_INGESTION_GATEWAY_CORS_ALLOW_ORIGINS"
_DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:4173",
    "http://localhost:4173",
    "http://127.0.0.1:5273",
    "http://localhost:5273",
    "http://127.0.0.1:5180",
    "http://localhost:5180",
    "http://127.0.0.1:5190",
    "http://localhost:5190",
)


def _cors_origins_from_env(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    env = environ if environ is not None else os.environ
    raw = env.get(_CORS_ORIGINS_ENV)
    if raw is None:
        return _DEFAULT_CORS_ORIGINS
    origins = tuple(value.strip().rstrip("/") for value in raw.split(",") if value.strip())
    if not origins:
        raise ValueError(f"{_CORS_ORIGINS_ENV} MUST contain at least one origin")
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            origin == "*"
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"{_CORS_ORIGINS_ENV} entries MUST be explicit HTTP(S) origins")
    return origins


def app() -> Starlette:
    """Build the in-memory local gateway; the boundary enforces the dev-mode env guard."""
    access = InMemoryDocumentAccessProvider(
        contributors={_LOCAL_COLLECTION: frozenset({_LOCAL_ACTOR})},
        readers={_LOCAL_COLLECTION: frozenset({_LOCAL_ACTOR})},
        owners={_LOCAL_COLLECTION: frozenset({_LOCAL_ACTOR})},
    )
    metadata = InMemoryDocumentMetadataStore()
    objects = InMemoryDocumentObjectStore()
    activity = RecordingDocumentActivitySink()
    capabilities = IngestionCapabilities(
        supported_formats=("text", "ooxml", "image-metadata", "pdf-detect-only"),
        storage_modes=tuple(SourceStorageMode),
        max_file_size=25 * 1024 * 1024,
        max_batch_count=10,
        archives_enabled=False,
        policy_versions=("local-policy-v1",),
    )
    service = DocumentIngestionService(
        access=access,
        metadata=metadata,
        objects=objects,
        activity=activity,
        capabilities=capabilities,
    )
    handover_drafts = InMemoryHandoverDraftStore()
    document_index = InMemoryEmbeddingDocumentIndex(embedder=DeterministicEmbeddingModel())
    worker = DocumentIngestionWorker(
        access=access,
        metadata=metadata,
        objects=objects,
        malware=StaticMalwareScanner(),
        protection=SignatureProtectionInspector(),
        extractor=StandardLibraryDocumentExtractor(),
        artifacts=InMemoryDocumentArtifactStore(),
        index=document_index,
        activity=activity,
        consumers=(
            HandoverBootstrapConsumer(
                bootstrapper=HandoverBootstrapper(),
                store=handover_drafts,
            ),
        ),
    )
    resolver = RoleResolver(
        group_mapping=GroupMapping(
            reader_group_id="reader-group",
            contributor_group_id="contributor-group",
            approver_group_id="approver-group",
            owner_group_id="owner-group",
            break_glass_group_id="break-glass-group",
        )
    )
    authenticator = build_authenticator(verifier=UnsafeClaimsExtractor(), resolver=resolver)
    application = build_app(
        authenticator=authenticator,
        service=service,
        worker=worker,
        search_index=document_index,
        handover_drafts=handover_drafts,
        config=IngestionGatewayConfig(
            dev_mode=True,
            direct_upload=True,
            cors_allow_origins=_cors_origins_from_env(),
            allowed_collections=(_LOCAL_COLLECTION,),
        ),
    )
    application.state.document_index = document_index
    return application


__all__ = ["app"]
