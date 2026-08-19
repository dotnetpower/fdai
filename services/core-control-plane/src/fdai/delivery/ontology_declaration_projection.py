"""Build bounded read-only declaration details from one reviewed ontology release."""

from __future__ import annotations

import hashlib
import json

from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.shared.contracts.models import (
    CEILING_ROLE_RANK,
    CeilingRole,
    OntologyDeclarationKind,
    OntologyObjectType,
)


def build_object_type_detail_projection(
    *,
    ontology: OntologyCatalog,
    name: str,
    role: CeilingRole,
    purpose: str,
    expected_release_digest: str | None = None,
) -> dict[str, object]:
    """Project one exact ObjectType after server-owned role and purpose filtering."""

    release = ontology.build_release()
    if expected_release_digest is not None and expected_release_digest != release.digest:
        raise ValueError("ontology declaration projection release does not match active release")

    object_type = _object_type(ontology, name)
    properties, redacted_count, redaction_reasons = _visible_properties(
        object_type,
        role=role,
        purpose=purpose,
    )
    declaration = object_type.model_dump(mode="json", exclude_none=True)
    declaration["properties"] = properties

    relationships = [
        {
            **link_type.model_dump(mode="json", exclude_none=True),
            "selected_type_direction": _selected_direction(
                selected_type=name,
                from_type=link_type.from_type,
                to_type=link_type.to_type,
            ),
        }
        for link_type in sorted(ontology.link_types, key=lambda item: item.name)
        if name in {link_type.from_type, link_type.to_type}
    ]
    implemented_interfaces = {
        interface_name
        for implementation in ontology.interface_implementations
        if implementation.object_type == name
        for interface_name in implementation.interfaces
    }
    release_declarations = {
        (
            declaration_ref.kind,
            declaration_ref.name,
            declaration_ref.version,
            declaration_ref.declaration_digest,
        )
        for declaration_ref in release.declarations
    }
    related_actions: list[dict[str, object]] = []
    unbound_action_count = 0
    for action_type in sorted(ontology.action_types, key=lambda item: item.name):
        semantic = action_type.semantic
        if semantic is None:
            unbound_action_count += 1
            continue
        target_ref = semantic.target.type_ref
        target_identity = (
            target_ref.kind,
            target_ref.name,
            target_ref.version,
            target_ref.declaration_digest,
        )
        if target_identity not in release_declarations:
            raise ValueError("ActionType semantic target is not a member of the active release")
        applies = (
            target_ref.kind is OntologyDeclarationKind.OBJECT and target_ref.name == name
        ) or (
            target_ref.kind is OntologyDeclarationKind.INTERFACE
            and target_ref.name in implemented_interfaces
        )
        if applies:
            related_actions.append(
                {
                    **action_type.model_dump(mode="json", exclude_none=True),
                    "target_evidence": semantic.target.model_dump(mode="json"),
                }
            )

    incomplete_reasons = ["action_target_evidence_unavailable"] if unbound_action_count else []
    visible: dict[str, object] = {
        "schema_version": "1.0.0",
        "ontology_release_digest": release.digest,
        "declaration_kind": "object_type",
        "declaration_name": object_type.name,
        "mutation_authority": False,
        "complete": not incomplete_reasons,
        "incomplete_reasons": incomplete_reasons,
        "redaction": {
            "redacted_field_count": redacted_count,
            "reasons": redaction_reasons,
        },
        "declaration": declaration,
        "relationships": relationships,
        "related_actions": related_actions,
    }
    visible["_revision"] = _projection_digest(visible)
    return visible


def build_link_type_detail_projection(
    *,
    ontology: OntologyCatalog,
    name: str,
    expected_release_digest: str | None = None,
) -> dict[str, object]:
    """Project one exact LinkType contract without deriving an inverse relationship."""

    release = ontology.build_release()
    _require_release(release.digest, expected_release_digest)
    matches = [item for item in ontology.link_types if item.name == name]
    if len(matches) != 1:
        raise LookupError(f"unknown LinkType declaration: {name}")
    visible: dict[str, object] = {
        "schema_version": "1.0.0",
        "ontology_release_digest": release.digest,
        "declaration_kind": "link_type",
        "declaration_name": name,
        "mutation_authority": False,
        "complete": True,
        "incomplete_reasons": [],
        "redaction": {"redacted_field_count": 0, "reasons": []},
        "declaration": matches[0].model_dump(mode="json", exclude_none=True),
        "relationships": [],
        "related_actions": [],
    }
    visible["_revision"] = _projection_digest(visible)
    return visible


def build_action_type_detail_projection(
    *,
    ontology: OntologyCatalog,
    name: str,
    expected_release_digest: str | None = None,
) -> dict[str, object]:
    """Project one exact ActionType safety contract without granting execution authority."""

    release = ontology.build_release()
    _require_release(release.digest, expected_release_digest)
    matches = [item for item in ontology.action_types if item.name == name]
    if len(matches) != 1:
        raise LookupError(f"unknown ActionType declaration: {name}")
    action_type = matches[0]
    semantic = action_type.semantic
    visible: dict[str, object] = {
        "schema_version": "1.0.0",
        "ontology_release_digest": release.digest,
        "declaration_kind": "action_type",
        "declaration_name": name,
        "mutation_authority": False,
        "complete": semantic is not None,
        "incomplete_reasons": (
            [] if semantic is not None else ["action_target_evidence_unavailable"]
        ),
        "redaction": {"redacted_field_count": 0, "reasons": []},
        "declaration": action_type.model_dump(mode="json", exclude_none=True),
        "relationships": [],
        "related_actions": [],
    }
    visible["_revision"] = _projection_digest(visible)
    return visible


def _object_type(ontology: OntologyCatalog, name: str) -> OntologyObjectType:
    matches = [item for item in ontology.object_types if item.name == name]
    if len(matches) != 1:
        raise LookupError(f"unknown ObjectType declaration: {name}")
    return matches[0]


def _require_release(active_digest: str, expected_digest: str | None) -> None:
    if expected_digest is not None and expected_digest != active_digest:
        raise ValueError("ontology declaration projection release does not match active release")


def _visible_properties(
    object_type: OntologyObjectType,
    *,
    role: CeilingRole,
    purpose: str,
) -> tuple[dict[str, object], int, list[str]]:
    properties: dict[str, object] = {}
    redacted_count = 0
    reasons: set[str] = set()
    for name, declaration in sorted(object_type.properties.items()):
        role_allowed = CEILING_ROLE_RANK[role] >= CEILING_ROLE_RANK[declaration.access_scope]
        purpose_allowed = not declaration.purpose_binding or purpose in declaration.purpose_binding
        if role_allowed and purpose_allowed:
            properties[name] = declaration.model_dump(mode="json")
            continue
        redacted_count += 1
        if not role_allowed:
            reasons.add("role")
        if not purpose_allowed:
            reasons.add("purpose")
    return properties, redacted_count, sorted(reasons)


def _selected_direction(*, selected_type: str, from_type: str, to_type: str) -> str:
    if from_type == selected_type == to_type:
        return "self"
    if from_type == selected_type:
        return "outgoing"
    return "incoming"


def _projection_digest(value: dict[str, object]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


__all__ = [
    "build_action_type_detail_projection",
    "build_link_type_detail_projection",
    "build_object_type_detail_projection",
]
