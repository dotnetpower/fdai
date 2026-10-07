"""Principal-scoped query manifest projection for semantic planning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fdai_service_contracts import canonical_ordinary_role
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform import QueryManifest, ReviewedPropertyRead, build_query_manifest
from fdai.core.ontology_platform.kubernetes_pod_recovery_queries import (
    KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT,
)
from fdai.core.ontology_platform.kubernetes_rollout_queries import (
    KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT,
)
from fdai.core.ontology_platform.metric_semantics import MetricSemanticRegistry
from fdai.core.ontology_platform.property_values import PropertyValueDomain
from fdai.core.ontology_platform.resource_health_values import resource_health_state_values
from fdai.rule_catalog.schema.inventory_query_language import InventoryQueryLanguageRegistry
from fdai.rule_catalog.schema.property_semantic import PropertySemanticRegistry
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
    property_semantics: PropertySemanticRegistry | None = None

    def metric_labels(self) -> dict[str, str]:
        registry = self.metric_registry
        if registry is None:
            return {}
        return {concept: item.description for concept, item in registry.definitions.items()}

    def metric_units(self) -> dict[str, str]:
        registry = self.metric_registry
        if registry is None:
            return {}
        return {concept: item.canonical_unit for concept, item in registry.definitions.items()}

    def metric_recipes(self) -> tuple[tuple[str, str, str, int, int], ...]:
        """Return each reviewed qualitative recipe as (concept, qualifier, comparator,
        threshold, window seconds or 0 when the goal's own window applies)."""

        registry = self.metric_registry
        if registry is None:
            return ()
        return tuple(
            sorted(
                (
                    concept,
                    recipe.qualifier,
                    recipe.comparator,
                    recipe.threshold,
                    recipe.window_seconds or 0,
                )
                for concept, item in registry.definitions.items()
                for recipe in item.qualitative_recipes
            )
        )

    def health_labels(self) -> dict[str, tuple[str, ...]]:
        language = self.inventory_query_language
        if language is None:
            return {}
        try:
            return resource_health_state_values(language)
        except ValueError:
            # A vocabulary without Resource Health groups offers no health concepts.
            return {}

    def property_reads(self) -> tuple[ReviewedPropertyRead, ...]:
        """Return each reviewed semantic with the one provider path per resource type.

        A resource type with more than one reviewed path for a semantic, such as one per
        provider, can't say which one a Resource carries, so that type is left out.
        """

        registry = self.property_semantics
        if registry is None:
            return ()
        reads: list[ReviewedPropertyRead] = []
        for semantic in registry.semantics:
            by_type: dict[str, list[str]] = {}
            for item in semantic.equivalent_provider_paths:
                by_type.setdefault(item.resource_type, []).append(item.path)
            paths = tuple(
                sorted((kind, found[0]) for kind, found in by_type.items() if len(found) == 1)
            )
            if paths:
                reads.append(
                    ReviewedPropertyRead(
                        semantic_id=semantic.semantic_id,
                        value_type=semantic.value_type.value,
                        unit=semantic.canonical_unit,
                        max_age_seconds=semantic.freshness.max_age_seconds,
                        paths=paths,
                    )
                )
        return tuple(reads)


def planner_metric_concepts(registry: MetricSemanticRegistry | None) -> tuple[str, ...]:
    """Return the symptom concepts and reviewed metric concepts the planner may bind."""

    reviewed = registry.definitions if registry is not None else ()
    return tuple(
        sorted(
            {KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT, KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT, *reviewed}
        )
    )


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
        self._metric_units: Mapping[str, str] = vocabulary.metric_units()
        self._metric_recipes = vocabulary.metric_recipes()
        self._health_labels: Mapping[str, tuple[str, ...]] = vocabulary.health_labels()
        self._property_reads = vocabulary.property_reads()
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
            property_reads=self._property_reads,
            metric_units=self._metric_units,
            metric_recipes=self._metric_recipes,
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
    "planner_metric_concepts",
    "semantic_principal_scope_digest",
]
