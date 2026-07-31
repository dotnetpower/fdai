"""Catalog-driven resource-type resolution for inventory questions."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import yaml

from fdai.delivery.read_api.routes.chat_inventory_language import (
    InventoryQueryLanguageResolver,
    default_inventory_query_language_resolver,
)
from fdai.delivery.read_api.routes.chat_inventory_query import normalize_inventory_value
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    load_resource_type_registry_from_mapping,
)


class InventoryResourceTypeResolver:
    """Resolve bounded natural-language terms to canonical resource-type ids."""

    def __init__(
        self,
        registry: ResourceTypeRegistry,
        language: InventoryQueryLanguageResolver | None = None,
    ) -> None:
        self._registry = registry
        self._language = language or default_inventory_query_language_resolver()
        self._type_forms = tuple(
            sorted(
                (
                    (normalize_inventory_value(term), entry.id)
                    for entry in registry
                    for term in (
                        entry.id,
                        entry.id.replace("-", " ").replace(".", " "),
                        *entry.query_terms,
                    )
                ),
                key=lambda item: (-len(item[0]), item[0], item[1]),
            )
        )
        self._category_forms = tuple(
            sorted(
                (
                    (normalize_inventory_value(term), category.value)
                    for category, terms in registry.category_query_terms.items()
                    for term in terms
                ),
                key=lambda item: (-len(item[0]), item[0], item[1]),
            )
        )

    def resolve(
        self,
        prompt: str,
        *,
        observed_types: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        """Return one longest exact type match, or a category expansion."""

        type_matches = [
            (surface, type_id)
            for surface, type_id in self._type_forms
            if self._language.contains_any(prompt, (surface,))
        ]
        if type_matches:
            return tuple(sorted({type_id for _surface, type_id in type_matches}))

        category_matches = [
            (surface, category)
            for surface, category in self._category_forms
            if self._language.contains_any(prompt, (surface,))
        ]
        if category_matches:
            longest = max(len(surface) for surface, _category in category_matches)
            categories = {
                category for surface, category in category_matches if len(surface) == longest
            }
            if len(categories) != 1:
                return ()
            category = next(iter(categories))
            return tuple(
                sorted(entry.id for entry in self._registry if entry.category.value == category)
            )

        return tuple(
            sorted(
                observed_type
                for observed_type in observed_types
                if self._language.contains_any(prompt, (normalize_inventory_value(observed_type),))
            )
        )

    def categories_for(self, type_ids: Sequence[str]) -> tuple[str, ...]:
        """Return catalog categories represented by canonical type ids."""

        selected = set(type_ids)
        return tuple(
            sorted({entry.category.value for entry in self._registry if entry.id in selected})
        )

    def provider_types_for(self, type_ids: Sequence[str]) -> tuple[str, ...]:
        """Return provider type identifiers for selected canonical resource types."""

        selected = set(type_ids)
        return tuple(
            sorted(
                entry.azure_arm_type
                for entry in self._registry
                if entry.id in selected and entry.azure_arm_type is not None
            )
        )


@lru_cache(maxsize=1)
def default_inventory_resource_type_resolver() -> InventoryResourceTypeResolver:
    """Load the shipped catalog once for direct and composed read-API callers."""

    repo_root = Path(__file__).resolve().parents[5]
    vocabulary_file = repo_root / "rule-catalog" / "vocabulary" / "resource-types.yaml"
    registry = load_resource_type_registry_from_mapping(
        yaml.safe_load(vocabulary_file.read_text(encoding="utf-8"))
    )
    return InventoryResourceTypeResolver(registry)


__all__ = [
    "InventoryResourceTypeResolver",
    "default_inventory_resource_type_resolver",
]
