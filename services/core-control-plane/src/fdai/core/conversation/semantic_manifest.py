"""Principal-scoped query manifest projection for semantic planning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fdai_service_contracts import canonical_ordinary_role
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform import QueryManifest, build_query_manifest
from fdai.core.ontology_platform.metric_semantics import MetricSemanticRegistry
from fdai.core.ontology_platform.property_values import PropertyValueDomain
from fdai.core.ontology_platform.resource_health_values import resource_health_state_values
from fdai.rule_catalog.schema.inventory_query_language import InventoryQueryLanguageRegistry
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyActionType,
    OntologyFunctionType,
    OntologyInterfaceType,
    OntologyLinkType,
    OntologyObjectType,
    OntologyRelease,
)

from .session import Principal, Role

_ROLE_MAP = {
    Role.READER: CeilingRole.READER,
    Role.CONTRIBUTOR: CeilingRole.CONTRIBUTOR,
    Role.APPROVER: CeilingRole.APPROVER,
    Role.OWNER: CeilingRole.OWNER,
}


@dataclass(frozen=True, slots=True)
class ConceptVocabularies:
    """Reviewed measure vocabularies that concept choosers may ground a mention in."""

    metric_registry: MetricSemanticRegistry | None = None
    inventory_query_language: InventoryQueryLanguageRegistry | None = None

    def metric_labels(self) -> dict[str, str]:
        registry = self.metric_registry
        if registry is None:
            return {}
        return {concept: item.description for concept, item in registry.definitions.items()}

    def health_labels(self) -> dict[str, tuple[str, ...]]:
        language = self.inventory_query_language
        return resource_health_state_values(language) if language is not None else {}


class CatalogQueryManifestProvider:
    """Build immutable planner metadata from one exact loaded catalog release."""

    def __init__(
        self,
        *,
        release: OntologyRelease,
        object_types: Sequence[OntologyObjectType] = (),
        link_types: Sequence[OntologyLinkType] = (),
        interfaces: Sequence[OntologyInterfaceType] = (),
        action_types: Sequence[OntologyActionType] = (),
        functions: Sequence[OntologyFunctionType] = (),
        bound_function_names: Sequence[str] | None = None,
        property_values: Sequence[PropertyValueDomain] = (),
        vocabularies: ConceptVocabularies | None = None,
    ) -> None:
        self._release = release
        self._object_types = tuple(object_types)
        self._link_types = tuple(link_types)
        self._interfaces = tuple(interfaces)
        self._action_types = tuple(action_types)
        self._functions = tuple(functions)
        self._property_values = tuple(property_values)
        # Reviewed metric and health concepts, offered to concept choosers.
        vocabulary = vocabularies or ConceptVocabularies()
        self._metric_labels: Mapping[str, str] = vocabulary.metric_labels()
        self._health_labels: Mapping[str, tuple[str, ...]] = vocabulary.health_labels()
        self._bound_function_names = (
            None if bound_function_names is None else tuple(bound_function_names)
        )

    def manifest_for(self, *, principal: Principal, purpose: str) -> QueryManifest:
        """Return only declarations readable by the verified role and purpose."""

        try:
            role = _ROLE_MAP[principal.role]
        except KeyError as exc:
            raise PermissionError("break-glass principals cannot use semantic planning") from exc
        scope_digest = semantic_principal_scope_digest(principal=principal, purpose=purpose)
        return build_query_manifest(
            release=self._release,
            principal_role=role,
            purposes=(purpose,),
            principal_scope_digest=scope_digest,
            object_types=self._object_types,
            link_types=self._link_types,
            interfaces=self._interfaces,
            action_types=self._action_types,
            functions=self._functions,
            bound_function_names=self._bound_function_names,
            property_values=self._property_values,
            metric_labels=self._metric_labels,
            health_labels=self._health_labels,
        )


def semantic_principal_scope_digest(*, principal: Principal, purpose: str) -> str:
    """Return the exact authenticated principal scope shared by planning and execution."""

    return content_digest(
        {
            "principal_id": principal.id,
            "role": canonical_ordinary_role(principal.role.value),
            "purpose": purpose,
            "groups": sorted(principal.groups),
        }
    )


__all__ = [
    "CatalogQueryManifestProvider",
    "ConceptVocabularies",
    "semantic_principal_scope_digest",
]
