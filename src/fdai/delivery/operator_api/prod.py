"""Stable production Operator API factory facade."""

from __future__ import annotations

from collections.abc import Mapping

from starlette.applications import Starlette

from fdai.delivery.operator_api.production.config import (
    ProdOperatorApiConfigError,
    _build_group_mapping,
    _check_required_env,
    _parse_cors_origins,
    _parse_positive_int,
    _plain_dsn,
    _require_env,
    build_prod_read_model,
)
from fdai.delivery.operator_api.production.views import _build_dynamic_views
from fdai.shared.providers.catalog_search import CatalogSemanticIndex


def build_prod_app(
    environ: Mapping[str, str] | None = None,
    *,
    catalog_semantic_index: CatalogSemanticIndex | None = None,
) -> Starlette:
    from fdai.delivery.operator_api.production.factory import build_prod_app as build

    return build(environ, catalog_semantic_index=catalog_semantic_index)


def app() -> Starlette:
    return build_prod_app()


__all__ = [
    "ProdOperatorApiConfigError",
    "_build_dynamic_views",
    "_build_group_mapping",
    "_check_required_env",
    "_parse_cors_origins",
    "_parse_positive_int",
    "_plain_dsn",
    "_require_env",
    "app",
    "build_prod_app",
    "build_prod_read_model",
]
