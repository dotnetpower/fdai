"""Grounded search-document projection for Rule catalog retrieval."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fdai.rule_catalog.schema.rego_semantics import RegoSemantics
from fdai.shared.contracts.models import OntologyActionType, Rule
from fdai.shared.providers.catalog_search import CatalogSearchDocument


def build_catalog_search_documents(
    *,
    rules: Sequence[Rule],
    action_types: Sequence[OntologyActionType],
    policy_semantics: Mapping[str, RegoSemantics],
) -> tuple[CatalogSearchDocument, ...]:
    actions = {item.name: item for item in action_types}
    documents = []
    for rule in sorted(rules, key=lambda item: item.id):
        policy = policy_semantics.get(rule.check_logic.reference)
        if policy is None or policy.rule_id != rule.id:
            raise ValueError(f"verified policy semantics unavailable for {rule.id!r}")
        action = actions.get(rule.remediates)
        if action is None:
            raise ValueError(f"ActionType unavailable for {rule.id!r}")
        action_description = action.description or ""
        text = "\n".join(
            (
                rule.id,
                rule.resource_type,
                rule.category.value,
                rule.severity.value,
                policy.title,
                policy.description,
                rule.remediates,
                action_description,
                *rule.triggered_by,
                *rule.evaluates,
            )
        )
        neighbors = tuple(
            sorted(
                {
                    rule.resource_type,
                    rule.remediates,
                    rule.check_logic.reference,
                    *rule.triggered_by,
                    *rule.evaluates,
                }
            )
        )
        documents.append(
            CatalogSearchDocument(
                rule_id=rule.id,
                text=text,
                neighbor_ids=neighbors,
            )
        )
    return tuple(documents)


__all__ = ["build_catalog_search_documents"]
