"""Catalog-driven resource-type resolution for inventory questions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path

import yaml

from fdai.delivery.operator_api.application.conversation.capabilities.inventory.language import (
    InventoryQueryLanguageResolver,
    default_inventory_query_language_resolver,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.query import (
    normalize_inventory_value,
)
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
        self._group_forms = tuple(
            sorted(
                (
                    (normalize_inventory_value(term), group.members)
                    for group in registry.query_groups
                    for term in group.terms
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

        group_matches = [
            (surface, members)
            for surface, members in self._group_forms
            if self._language.contains_any(prompt, (surface,))
        ]
        if group_matches:
            longest = max(len(surface) for surface, _members in group_matches)
            member_sets = {members for surface, members in group_matches if len(surface) == longest}
            if len(member_sets) == 1:
                return tuple(sorted(next(iter(member_sets))))

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

    def is_exact_reference(self, prompt: str) -> bool:
        """Return whether the complete prompt is one catalog resource-type surface."""

        return any(
            self._language.is_exact(prompt, (surface,))
            for surface, _value in (*self._type_forms, *self._category_forms, *self._group_forms)
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

    def provider_kind_tokens_for(
        self,
        type_ids: Sequence[str],
    ) -> Mapping[str, tuple[str, ...]]:
        """Return Azure kind tokens keyed by selected provider resource type."""

        selected = set(type_ids)
        return {
            entry.azure_arm_type: entry.azure_kind_tokens
            for entry in self._registry
            if entry.id in selected and entry.azure_arm_type is not None and entry.azure_kind_tokens
        }


@lru_cache(maxsize=1)
def default_inventory_resource_type_resolver() -> InventoryResourceTypeResolver:
    """Load the shipped catalog once for direct and composed Operator API callers."""

    repo_root = Path(__file__).resolve().parents[8]
    vocabulary_file = repo_root / "rule-catalog" / "vocabulary" / "resource-types.yaml"
    registry = load_resource_type_registry_from_mapping(
        yaml.safe_load(vocabulary_file.read_text(encoding="utf-8"))
    )
    return InventoryResourceTypeResolver(registry)


__all__ = [
    "InventoryResourceTypeResolver",
    "default_inventory_resource_type_resolver",
]
