"""Canonical ontology release construction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyDeclarationRef,
    OntologyFunctionType,
    OntologyInterfaceType,
    OntologyLinkType,
    OntologyObjectType,
    OntologyRelease,
)


def build_ontology_release(
    *,
    object_types: Sequence[OntologyObjectType] = (),
    link_types: Sequence[OntologyLinkType] = (),
    action_types: Sequence[OntologyActionType] = (),
    interface_types: Sequence[OntologyInterfaceType] = (),
    function_types: Sequence[OntologyFunctionType] = (),
) -> OntologyRelease:
    """Build one deterministic release over the supplied declarations."""

    declarations = canonical_ontology_declarations(
        (
            *(_declaration_ref(OntologyDeclarationKind.OBJECT, item) for item in object_types),
            *(_declaration_ref(OntologyDeclarationKind.LINK, item) for item in link_types),
            *(_declaration_ref(OntologyDeclarationKind.ACTION, item) for item in action_types),
            *(
                _declaration_ref(OntologyDeclarationKind.INTERFACE, item)
                for item in interface_types
            ),
            *(_declaration_ref(OntologyDeclarationKind.FUNCTION, item) for item in function_types),
        )
    )
    return OntologyRelease(
        digest=ontology_release_digest(declarations),
        declarations=declarations,
    )


def canonical_ontology_declarations(
    declarations: Sequence[OntologyDeclarationRef],
) -> tuple[OntologyDeclarationRef, ...]:
    """Return declarations in the one canonical release order."""

    return tuple(
        sorted(
            declarations,
            key=lambda item: (item.kind.value, item.name, item.version),
        )
    )


def ontology_release_digest(declarations: Sequence[OntologyDeclarationRef]) -> str:
    """Return the canonical digest for an ordered declaration sequence."""

    return _digest([item.model_dump(mode="json") for item in declarations])


def validate_ontology_release(release: OntologyRelease) -> None:
    """Reject duplicate, noncanonical, or digest-inconsistent release content."""

    identities = {(item.kind, item.name) for item in release.declarations}
    if len(identities) != len(release.declarations):
        raise ValueError("ontology release declaration identities MUST be unique")
    if release.declarations != canonical_ontology_declarations(release.declarations):
        raise ValueError("ontology release declarations MUST use canonical order")
    if release.digest != ontology_release_digest(release.declarations):
        raise ValueError("ontology release digest does not match declarations")


def _declaration_ref(
    kind: OntologyDeclarationKind,
    declaration: (
        OntologyObjectType
        | OntologyLinkType
        | OntologyActionType
        | OntologyInterfaceType
        | OntologyFunctionType
    ),
) -> OntologyDeclarationRef:
    return OntologyDeclarationRef(
        kind=kind,
        name=declaration.name,
        version=declaration.version,
        declaration_digest=_digest(_release_payload(declaration)),
    )


_HISTORICAL_TRAIT_LINKS = frozenset(
    {
        "attached_to",
        "capacity_forecast_targets_resource",
        "change_targets_resource",
        "contains",
        "cost_anomaly_derived_from",
        "cost_observation_targets_resource",
        "depends_on",
        "diagnostic_finding_affects_resource",
        "drift_finding_affects_resource",
        "emits_to",
        "kubernetes_backed_by",
        "kubernetes_exposes_endpoint_slice",
        "kubernetes_exposes_endpoints",
        "kubernetes_owned_by",
        "kubernetes_scheduled_on",
        "kubernetes_selects",
        "observation_targets_resource",
        "owns",
        "peered_with",
        "recovery_targets_resource",
        "resource_class_specializes",
        "resource_classified_as",
        "resource_of",
        "resource_type_member_of_class",
        "routes_to",
        "runs_on",
        "runtime_calls",
        "scoped_to",
        "sizing_recommendation_based_on",
        "sizing_recommendation_targets_resource",
        "summarizes",
        "targets",
        "workload_runs_on",
    }
)
_HISTORICAL_ROLE_LINKS = frozenset(
    {
        "attached_to",
        "budget_implements_cost_objective",
        "capacity_forecast_targets_resource",
        "contains",
        "cost_anomaly_derived_from",
        "cost_observation_targets_resource",
        "depends_on",
        "kubernetes_backed_by",
        "kubernetes_exposes_endpoint_slice",
        "peered_with",
        "resource_class_specializes",
        "resource_classified_as",
        "resource_type_member_of_class",
        "routes_to",
        "runtime_calls",
        "service_has_budget",
        "sizing_recommendation_based_on",
        "sizing_recommendation_targets_resource",
    }
)


def _release_payload(
    declaration: (
        OntologyObjectType
        | OntologyLinkType
        | OntologyActionType
        | OntologyInterfaceType
        | OntologyFunctionType
    ),
) -> dict[str, Any]:
    payload = declaration.model_dump(mode="json", exclude_none=True)
    if isinstance(declaration, OntologyObjectType):
        payload.pop("query_terms", None)
        payload.pop("authority_class", None)
        payload.pop("freshness_max_age_seconds", None)
    if isinstance(declaration, OntologyLinkType):
        if declaration.version == "1.0.0":
            if declaration.name not in _HISTORICAL_TRAIT_LINKS:
                payload["semantic_traits"] = []
            if declaration.name not in _HISTORICAL_ROLE_LINKS:
                payload.pop("forward_role", None)
                payload.pop("reverse_role", None)
        provenance = payload.get("provenance")
        if isinstance(provenance, dict) and "content_hash" in provenance:
            link_without_prov = dict(payload)
            link_without_prov.pop("provenance", None)
            if link_without_prov.get("semantic_traits") == []:
                link_without_prov.pop("semantic_traits", None)
            provenance["content_hash"] = _digest(link_without_prov)
    if isinstance(declaration, OntologyObjectType | OntologyInterfaceType):
        properties = payload.get("properties")
        if isinstance(properties, dict):
            for property_payload in properties.values():
                if not isinstance(property_payload, dict):
                    continue
                property_payload.pop("query_terms", None)
                property_payload.pop("value_query_terms", None)
        provenance = payload.get("provenance")
        if isinstance(provenance, dict) and "content_hash" in provenance:
            payload_without_provenance = dict(payload)
            payload_without_provenance.pop("provenance", None)
            provenance["content_hash"] = _digest(payload_without_provenance)
    return payload


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = ["build_ontology_release"]
