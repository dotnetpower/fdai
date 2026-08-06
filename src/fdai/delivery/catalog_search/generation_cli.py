"""One-shot entry point for publishing a validated catalog search generation."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from fdai.delivery.catalog_search.indexer import publish_shipped_catalog_generation
from fdai.delivery.operator_api.production.catalog_search import (
    ProductionCatalogSearch,
    build_production_catalog_search,
)
from fdai.shared.providers.catalog_search import CatalogGenerationMetadata

_DATABASE_URL_ENV = "FDAI_DATABASE_URL"
_EMBEDDING_DIM_ENV = "FDAI_EMBEDDING_DIM"


class CatalogGenerationCliError(RuntimeError):
    """The one-shot generation worker cannot run from its bounded configuration."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fdai-catalog-generation")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--opa-binary", default="opa")
    parser.add_argument("--validation-receipt-digest", required=True)
    parser.add_argument("--embedding-space-id", required=True)
    parser.add_argument("--embedding-model-version", required=True)
    return parser


def _psycopg_dsn(env: Mapping[str, str]) -> str:
    database_url = env.get(_DATABASE_URL_ENV, "").strip()
    if not database_url:
        raise CatalogGenerationCliError(f"{_DATABASE_URL_ENV} is required")
    if database_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + database_url[len("postgresql+psycopg://") :]
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise CatalogGenerationCliError(
            f"{_DATABASE_URL_ENV} MUST be a PostgreSQL psycopg-compatible URL"
        )
    return database_url


async def _publish(
    *,
    args: argparse.Namespace,
    env: Mapping[str, str],
) -> CatalogGenerationMetadata:
    production: ProductionCatalogSearch = build_production_catalog_search(
        env=env,
        dsn=_psycopg_dsn(env),
    )
    try:
        if production.index is None:
            raise CatalogGenerationCliError(
                "catalog semantic index is unavailable; configure and enable catalog search"
            )
        try:
            embedding_dimension = int(env.get(_EMBEDDING_DIM_ENV, "384"))
        except ValueError as exc:
            raise CatalogGenerationCliError(f"{_EMBEDDING_DIM_ENV} MUST be an integer") from exc
        return await publish_shipped_catalog_generation(
            index=production.index,
            repo_root=args.repo_root.resolve(),
            validation_receipt_digest=args.validation_receipt_digest,
            embedding_space_id=args.embedding_space_id,
            embedding_model_version=args.embedding_model_version,
            embedding_dimension=embedding_dimension,
            activated_at=datetime.now(tz=UTC),
            opa_binary=args.opa_binary,
        )
    finally:
        for callback in reversed(production.shutdown_callbacks):
            await callback()


def _projection(metadata: CatalogGenerationMetadata) -> dict[str, object]:
    return {
        "generation_id": metadata.generation_id,
        "generation_digest": metadata.generation_digest,
        "corpus": metadata.corpus,
        "catalog_digest": metadata.catalog_digest,
        "semantic_schema_digest": metadata.semantic_schema_digest,
        "ontology_release_digest": metadata.ontology_release_digest,
        "embedding_space_id": metadata.embedding_space_id,
        "embedding_model_version": metadata.embedding_model_version,
        "embedding_dimension": metadata.embedding_dimension,
        "state": metadata.state,
        "validation_receipt_digest": metadata.validation_receipt_digest,
        "activated_at": metadata.activated_at.isoformat() if metadata.activated_at else None,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        metadata = asyncio.run(_publish(args=args, env=os.environ))
    except (CatalogGenerationCliError, OSError, RuntimeError, ValueError) as exc:
        print(f"catalog generation failed: {exc}", file=sys.stderr)
        return 4
    print(json.dumps(_projection(metadata), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CatalogGenerationCliError", "main"]
