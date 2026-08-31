"""Non-authoritative framework catalog projection."""

from __future__ import annotations

from collections.abc import Sequence

from fdai.core.ontology_platform.catalog_projection import CatalogOntologyProjection
from fdai.rule_catalog.schema.control_objective import ControlObjective
from fdai.rule_catalog.schema.framework_catalog import FrameworkDefinition
from fdai.shared.providers.ontology_instance import (
    OntologyLinkRecord,
    OntologyObjectRecord,
)


def build_framework_catalog_projection(
    *,
    frameworks: Sequence[FrameworkDefinition],
    objectives: Sequence[ControlObjective],
) -> CatalogOntologyProjection:
    """Project framework meaning without producing assessment or authority facts."""

    objects: list[OntologyObjectRecord] = []
    links: list[OntologyLinkRecord] = []
    objective_ids = {
        objective.ref: f"control-objective:{objective.ref}" for objective in objectives
    }
    for objective in objectives:
        objects.append(
            OntologyObjectRecord(
                id=objective_ids[objective.ref],
                object_type="ControlObjective",
                properties={
                    "id": objective_ids[objective.ref],
                    "version": objective.version,
                    "title": objective.title,
                    "operating_domain": objective.operating_domain,
                    "predicate_family": objective.predicate_family,
                    "state": objective.state.value,
                    "content_digest": objective.content_digest,
                },
            )
        )
    for framework in frameworks:
        framework_id = f"framework:{framework.id}@{framework.version}"
        objects.append(
            OntologyObjectRecord(
                id=framework_id,
                object_type="Framework",
                properties={
                    "id": framework_id,
                    "version": framework.version,
                    "name": framework.name,
                    "scope": framework.scope,
                    "advisory": framework.advisory,
                    "completeness_scope": framework.completeness_scope,
                },
            )
        )
        for resolved in framework.resolved_controls():
            control = resolved.control
            control_id = f"framework-control:{framework.id}:{control.id}@{framework.version}"
            properties: dict[str, object] = {
                "id": control_id,
                "framework_id": framework.id,
                "control_id": control.id,
                "area": resolved.area or "methodology",
                "title": control.title,
                "mapping_status": control.mapping_status.value,
                "source_url": resolved.source_url,
                "source_version": resolved.source_version,
                "resolved_ref": resolved.resolved_ref,
            }
            if control.best_practice_ref is not None:
                properties["best_practice_ref"] = control.best_practice_ref
            if control.wara is not None:
                properties.update(
                    {
                        "recommendation_control": control.wara.control,
                        "recommendation_impact": control.wara.impact,
                        "resource_type": control.wara.resource_type,
                        "metadata_state": control.wara.state,
                        "product_group_verified": (control.wara.product_group_verified),
                        "automation_available": control.wara.automation_available,
                        "tags": list(control.wara.tags),
                        "potential_benefits": control.wara.potential_benefits,
                    }
                )
                if control.wara.query_digest is not None:
                    properties["query_digest"] = control.wara.query_digest
            objects.append(
                OntologyObjectRecord(
                    id=control_id,
                    object_type="FrameworkControl",
                    properties=properties,
                )
            )
            links.append(
                OntologyLinkRecord(
                    from_id=framework_id,
                    link_type="framework_contains_control",
                    to_id=control_id,
                )
            )
            for objective_ref in control.objective_refs:
                links.append(
                    OntologyLinkRecord(
                        from_id=control_id,
                        link_type="framework_control_maps_objective",
                        to_id=objective_ids[objective_ref],
                    )
                )
    return CatalogOntologyProjection(
        objects=tuple(sorted(objects, key=lambda item: item.id)),
        links=tuple(
            sorted(
                links,
                key=lambda item: (item.from_id, item.link_type, item.to_id),
            )
        ),
    )


__all__ = ["build_framework_catalog_projection"]
