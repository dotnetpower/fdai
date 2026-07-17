"""Catalog-driven view and user-context wiring for the local read API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai.delivery.read_api.dev.catalog_wiring import (
    LocalCatalogWiring,
    build_local_catalog_wiring,
)
from fdai.delivery.read_api.dev.fixtures.dynamic_views import (
    _build_dynamic_process_views_sync,
)
from fdai.delivery.read_api.dev.user_context import build_local_user_context


@dataclass(frozen=True, slots=True)
class LocalViewWiring:
    catalog: LocalCatalogWiring
    reporting: Any
    process_views: Any
    workflow_execution: Any
    user_context: Any


def build_local_view_wiring(*, repo_root: Path, read_model: Any) -> LocalViewWiring:
    """Build local catalogs, dynamic process views, and user context."""
    catalog = build_local_catalog_wiring(repo_root)
    reporting = None
    process_views = None
    workflow_execution = None
    if catalog.object_types and catalog.link_types and catalog.workflows:
        reporting, process_views, workflow_execution = _build_dynamic_process_views_sync(
            read_model=read_model,
            object_types=catalog.object_types,
            link_types=catalog.link_types,
            workflows=catalog.workflows,
            action_types=catalog.action_types,
        )
    user_context = build_local_user_context(
        schema_registry=catalog.schema_registry,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        action_types=catalog.action_types,
        workflows=catalog.workflows,
        rule_ids=frozenset(rule.id for rule in catalog.rules if getattr(rule, "id", None)),
    )
    return LocalViewWiring(
        catalog=catalog,
        reporting=reporting,
        process_views=process_views,
        workflow_execution=workflow_execution,
        user_context=user_context,
    )


__all__ = ["LocalViewWiring", "build_local_view_wiring"]
