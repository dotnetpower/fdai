"""Catalog-driven natural-language compiler for verified inventory queries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai.delivery.operator_api.routes.chat_inventory_language import (
    InventoryQueryLanguageResolver,
    default_inventory_query_language_resolver,
)
from fdai.delivery.operator_api.routes.chat_inventory_query import (
    InventoryField,
    InventoryOperator,
    InventoryPredicate,
    InventoryQuery,
    InventoryQueryGrouping,
    InventoryQueryKind,
    InventoryQueryProjection,
    InventoryQueryScope,
    InventoryQuerySource,
    InventoryQueryValueGroup,
    normalize_inventory_value,
)
from fdai.delivery.operator_api.routes.chat_inventory_resource_types import (
    InventoryResourceTypeResolver,
    default_inventory_resource_type_resolver,
)
from fdai.rule_catalog.schema.inventory_query_language import QueryEvidenceAuthority


def is_inventory_question(
    prompt: str,
    *,
    resolver: InventoryResourceTypeResolver | None = None,
    language: InventoryQueryLanguageResolver | None = None,
) -> bool:
    """Return whether catalog signals identify a bounded inventory read."""

    lexical = language or default_inventory_query_language_resolver()
    registry = lexical.registry
    resource_types = _resolver(resolver).resolve(prompt)
    matched_states = lexical.matched_entries(registry.states, prompt)
    diagnosis_allowed = bool(resource_types) and any(
        entry.evidence_authority is QueryEvidenceAuthority.SUBSCRIPTION_HEALTH
        for entry in matched_states
    )
    semantic_marker = bool(
        matched_states
        or lexical.matched_value_groups(registry.operations, prompt)
        or lexical.matched_ids(registry.query_kinds, prompt)
        or lexical.matched_ids(registry.groupings, prompt)
        or lexical.has(registry.signals, "workload", prompt)
    )
    return bool(
        prompt.strip()
        and not lexical.has(registry.signals, "mutation", prompt)
        and (not lexical.has(registry.signals, "diagnosis", prompt) or diagnosis_allowed)
        and (lexical.has(registry.signals, "resource_subject", prompt) or resource_types)
        and (lexical.has(registry.signals, "read", prompt) or semantic_marker or "?" in prompt)
    )


def is_specific_inventory_question(
    prompt: str,
    *,
    resolver: InventoryResourceTypeResolver | None = None,
    language: InventoryQueryLanguageResolver | None = None,
) -> bool:
    """Return whether an inventory read selects a concrete resource family."""

    resource_type_resolver = _resolver(resolver)
    resource_types = _resource_types(prompt, (), resolver=resource_type_resolver)
    return is_inventory_question(
        prompt,
        resolver=resource_type_resolver,
        language=language,
    ) and bool(set(resource_types) - {"subscription"})


def compile_inventory_query(
    prompt: str,
    *,
    resources: Sequence[Mapping[str, Any]] = (),
    resolver: InventoryResourceTypeResolver | None = None,
    language: InventoryQueryLanguageResolver | None = None,
) -> InventoryQuery | None:
    """Compile one high-confidence catalog match into a verified typed query."""

    lexical = language or default_inventory_query_language_resolver()
    registry = lexical.registry
    resource_type_resolver = _resolver(resolver)
    if not is_inventory_question(
        prompt,
        resolver=resource_type_resolver,
        language=lexical,
    ):
        return None

    resource_types = _resource_types(prompt, resources, resolver=resource_type_resolver)
    group = _facet_value(prompt, resources, "resource_group", language=lexical)
    if group:
        resource_types = tuple(item for item in resource_types if item != "resource-group")
    typed_resources = tuple(
        item for item in resources if not resource_types or item.get("type") in resource_types
    )
    name = _facet_value(prompt, typed_resources, "name", language=lexical)
    if (
        name is not None
        and group is not None
        and (normalize_inventory_value(name) == normalize_inventory_value(group))
    ):
        name = None
    operations = lexical.matched_values(registry.operations, prompt)
    source = _source(prompt, operations=operations, language=lexical)
    kind = _kind(prompt, source, language=lexical)
    if kind is InventoryQueryKind.SCOPE_COUNTS:
        resource_types = ()
        group = None
        name = None

    predicates: list[InventoryPredicate] = []
    if resource_types:
        predicates.append(_in_or_eq(InventoryField.RESOURCE_TYPE, resource_types))
    if group:
        predicates.append(
            InventoryPredicate(InventoryField.RESOURCE_GROUP, InventoryOperator.EQ, group)
        )
        if not resource_types:
            predicates.append(
                InventoryPredicate(
                    InventoryField.RESOURCE_TYPE,
                    InventoryOperator.NE,
                    "resource-group",
                )
            )
            predicates.append(
                InventoryPredicate(
                    InventoryField.PROVIDER_TYPE,
                    InventoryOperator.EXISTS,
                )
            )
    if name:
        predicates.append(InventoryPredicate(InventoryField.NAME, InventoryOperator.CONTAINS, name))

    if source is InventoryQuerySource.ACTIVITY:
        if operations:
            predicates.append(_in_or_eq(InventoryField.OPERATION, operations))
        predicates.append(
            InventoryPredicate(InventoryField.EVENT_STATUS, InventoryOperator.EQ, "succeeded")
        )
        return InventoryQuery(
            source=source,
            kind=kind,
            predicates=tuple(predicates),
            lookback_seconds=(
                lexical.parse_window_seconds(prompt) or registry.default_activity_lookback_seconds
            ),
            scope=_scope(prompt, language=lexical),
            group_by=_grouping(prompt, language=lexical),
            projection=_projection(prompt, language=lexical),
        )

    coverage_kind = kind in {
        InventoryQueryKind.INVENTORY_COVERAGE,
        InventoryQueryKind.STATE_COVERAGE,
    }
    statuses = (
        ()
        if coverage_kind
        else _status_values(
            prompt,
            resources,
            resource_types=resource_types,
            language=lexical,
            resolver=resource_type_resolver,
        )
    )
    if statuses:
        predicates.append(_in_or_eq(InventoryField.STATUS, statuses))
    location = _facet_value(prompt, typed_resources, "location", language=lexical)
    if location:
        predicates.append(
            InventoryPredicate(InventoryField.LOCATION, InventoryOperator.EQ, location)
        )
    if (
        not predicates
        and not lexical.matched_ids(registry.query_kinds, prompt)
        and not lexical.matched_ids(registry.groupings, prompt)
        and not lexical.has(registry.signals, "unfiltered", prompt)
    ):
        return None
    status_groups = (
        ()
        if coverage_kind
        else inventory_query_status_groups(
            prompt,
            resource_types=resource_types,
            language=lexical,
            resolver=resource_type_resolver,
        )
    )
    grouping = _grouping(prompt, language=lexical)
    if grouping is InventoryQueryGrouping.NONE and len(status_groups) > 1:
        grouping = InventoryQueryGrouping.STATUS
    return InventoryQuery(
        source=source,
        kind=kind,
        predicates=tuple(predicates),
        scope=_scope(prompt, language=lexical),
        group_by=grouping,
        projection=_projection(prompt, language=lexical),
        require_fresh=registry.current_requires_fresh,
        include_workloads=lexical.has(registry.signals, "workload", prompt),
        require_state_history=lexical.has(registry.signals, "temporal", prompt),
        status_groups=status_groups,
    )


def inventory_query_scope(
    prompt: str,
    *,
    language: InventoryQueryLanguageResolver | None = None,
) -> InventoryQueryScope:
    """Resolve only the server-owned scope before evidence-dependent facets."""

    lexical = language or default_inventory_query_language_resolver()
    return _scope(prompt, language=lexical)


def inventory_query_evidence_authorities(
    prompt: str,
    *,
    resolver: InventoryResourceTypeResolver | None = None,
    language: InventoryQueryLanguageResolver | None = None,
) -> tuple[QueryEvidenceAuthority, ...]:
    """Return catalog-owned authorities required by matched state semantics."""

    lexical = language or default_inventory_query_language_resolver()
    if not is_inventory_question(prompt, resolver=resolver, language=lexical):
        return ()
    matched_kinds = set(lexical.matched_ids(lexical.registry.query_kinds, prompt))
    if matched_kinds & {
        InventoryQueryKind.INVENTORY_COVERAGE.value,
        InventoryQueryKind.STATE_COVERAGE.value,
    }:
        return ()
    return tuple(
        dict.fromkeys(
            entry.evidence_authority
            for entry in lexical.registry.states.values()
            if lexical.contains_any(prompt, entry.terms)
        )
    )


def inventory_query_status_groups(
    prompt: str,
    *,
    resource_types: Sequence[str] = (),
    resolver: InventoryResourceTypeResolver | None = None,
    language: InventoryQueryLanguageResolver | None = None,
) -> tuple[InventoryQueryValueGroup, ...]:
    """Compile matched catalog state semantics for evidence and rendering."""

    lexical = language or default_inventory_query_language_resolver()
    resource_type_resolver = _resolver(resolver)
    groups = tuple(
        InventoryQueryValueGroup(
            id=entry_id,
            values=values,
            labels=lexical.registry.states[entry_id].labels,
        )
        for entry_id, values, _preserve in _state_groups(
            prompt,
            resource_types=resource_types,
            language=lexical,
            resolver=resource_type_resolver,
        )
    )
    return _disjoint_value_groups(groups)


def _disjoint_value_groups(
    groups: Sequence[InventoryQueryValueGroup],
) -> tuple[InventoryQueryValueGroup, ...]:
    """Assign overlapping values to the most specific requested semantic group."""

    value_sets = [set(group.values) for group in groups]
    normalized: list[InventoryQueryValueGroup] = []
    for index, group in enumerate(groups):
        values = value_sets[index].copy()
        for other_index, other_values in enumerate(value_sets):
            if other_index != index and other_values < value_sets[index]:
                values.difference_update(other_values)
        if values:
            normalized.append(
                InventoryQueryValueGroup(
                    id=group.id,
                    values=tuple(value for value in group.values if value in values),
                    labels=group.labels,
                )
            )
    return tuple(normalized)


def _source(
    prompt: str,
    *,
    operations: Sequence[str],
    language: InventoryQueryLanguageResolver,
) -> InventoryQuerySource:
    registry = language.registry
    if language.has(registry.signals, "activity", prompt) or (
        operations and language.has(registry.signals, "temporal", prompt)
    ):
        return InventoryQuerySource.ACTIVITY
    return InventoryQuerySource.CURRENT


def _kind(
    prompt: str,
    source: InventoryQuerySource,
    *,
    language: InventoryQueryLanguageResolver,
) -> InventoryQueryKind:
    matched = language.matched_ids(language.registry.query_kinds, prompt)
    priority = (
        InventoryQueryKind.SCOPE_COUNTS,
        InventoryQueryKind.INVENTORY_COVERAGE,
        InventoryQueryKind.STATE_COVERAGE,
        InventoryQueryKind.RELATIONSHIPS,
        InventoryQueryKind.TYPES,
        InventoryQueryKind.COUNT,
    )
    for candidate in priority:
        if candidate.value in matched and not (
            candidate is InventoryQueryKind.RELATIONSHIPS
            and source is InventoryQuerySource.ACTIVITY
        ):
            return candidate
    return InventoryQueryKind.LIST


def _scope(
    prompt: str,
    *,
    language: InventoryQueryLanguageResolver,
) -> InventoryQueryScope:
    matched = language.matched_ids(language.registry.scopes, prompt)
    selected = matched[0] if len(matched) == 1 else language.registry.default_scope
    return InventoryQueryScope(selected)


def _grouping(
    prompt: str,
    *,
    language: InventoryQueryLanguageResolver,
) -> InventoryQueryGrouping:
    matched = language.matched_ids(language.registry.groupings, prompt)
    if len(matched) != 1:
        return InventoryQueryGrouping.NONE
    return InventoryQueryGrouping(matched[0])


def _projection(
    prompt: str,
    *,
    language: InventoryQueryLanguageResolver,
) -> InventoryQueryProjection:
    matched = language.matched_ids(language.registry.projections, prompt)
    if len(matched) != 1:
        return InventoryQueryProjection.DETAILS
    return InventoryQueryProjection(matched[0])


def _resource_types(
    prompt: str,
    resources: Sequence[Mapping[str, Any]],
    *,
    resolver: InventoryResourceTypeResolver,
) -> tuple[str, ...]:
    observed = tuple(
        sorted(
            {
                str(item.get("type"))
                for item in resources
                if isinstance(item.get("type"), str) and item.get("type")
            }
        )
    )
    return resolver.resolve(prompt, observed_types=observed)


def _resolver(
    resolver: InventoryResourceTypeResolver | None,
) -> InventoryResourceTypeResolver:
    return resolver or default_inventory_resource_type_resolver()


def _status_values(
    prompt: str,
    resources: Sequence[Mapping[str, Any]],
    *,
    resource_types: Sequence[str],
    language: InventoryQueryLanguageResolver,
    resolver: InventoryResourceTypeResolver,
) -> tuple[str, ...]:
    observed = {
        normalize_inventory_value(item["status"])
        for item in resources
        if item.get("status") not in (None, "")
        and (not resource_types or str(item.get("type")) in resource_types)
    }
    matched: list[str] = []
    for _entry_id, requested, preserve in _state_groups(
        prompt,
        resource_types=resource_types,
        language=language,
        resolver=resolver,
    ):
        observed_group = sorted(
            status for status in observed if status.rsplit(" ", 1)[-1] in requested
        )
        matched.extend(requested if preserve else observed_group or requested)
    represented = {status.rsplit(" ", 1)[-1] for status in matched}
    for group in inventory_query_status_groups(
        prompt,
        resource_types=resource_types,
        resolver=resolver,
        language=language,
    ):
        if represented.isdisjoint(group.values):
            matched.extend(group.values)
            represented.update(group.values)
    matched.extend(
        status for status in sorted(observed) if language.contains_any(prompt, (status,))
    )
    return tuple(dict.fromkeys(matched))


def _state_groups(
    prompt: str,
    *,
    resource_types: Sequence[str],
    language: InventoryQueryLanguageResolver,
    resolver: InventoryResourceTypeResolver,
) -> tuple[tuple[str, tuple[str, ...], bool], ...]:
    categories = resolver.categories_for(resource_types)
    matched_entries = tuple(
        (entry_id, entry)
        for entry_id, entry in language.registry.states.items()
        if language.contains_any(prompt, entry.terms)
    )
    suppressed = {
        suppressed_id for _entry_id, entry in matched_entries for suppressed_id in entry.suppresses
    }
    groups: list[tuple[str, tuple[str, ...], bool]] = []
    for entry_id, entry in matched_entries:
        if entry_id in suppressed:
            continue
        category = categories[0] if len(categories) == 1 else None
        values = entry.category_values.get(category, entry.values) if category else entry.values
        preserve = entry.preserve_values or category in entry.preserve_categories
        groups.append((entry_id, values, preserve))
    return tuple(groups)


def _facet_value(
    prompt: str,
    resources: Sequence[Mapping[str, Any]],
    field: str,
    *,
    language: InventoryQueryLanguageResolver,
) -> str | None:
    values = sorted(
        {str(item[field]) for item in resources if item.get(field) not in (None, "")},
        key=len,
        reverse=True,
    )
    return next(
        (value for value in values if language.contains_any(prompt, (value,))),
        None,
    )


def _in_or_eq(field: InventoryField, values: Sequence[str]) -> InventoryPredicate:
    unique = tuple(dict.fromkeys(values))
    return InventoryPredicate(
        field,
        InventoryOperator.EQ if len(unique) == 1 else InventoryOperator.IN,
        unique[0] if len(unique) == 1 else unique,
    )


__all__ = [
    "compile_inventory_query",
    "inventory_query_evidence_authorities",
    "inventory_query_status_groups",
    "inventory_query_scope",
    "is_inventory_question",
]
