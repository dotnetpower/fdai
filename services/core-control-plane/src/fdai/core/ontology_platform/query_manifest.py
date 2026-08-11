"""Principal-scoped planner descriptors derived from one exact ontology release."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fdai_service_contracts.ontology_query import (
    StructuralCoverageReceipt,
    content_digest,
)

from fdai.shared.contracts.models import (
    CEILING_ROLE_RANK,
    CeilingRole,
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyFunctionType,
    OntologyInterfaceType,
    OntologyLinkType,
    OntologyObjectType,
    OntologyRelease,
)

_MAX_MANIFEST_BYTES = 8_388_608


@dataclass(frozen=True, slots=True)
class QueryManifest:
    """Immutable planner-facing descriptors and their coverage receipt."""

    release_digest: str
    principal_role: CeilingRole
    purposes: tuple[str, ...]
    descriptors: tuple[dict[str, Any], ...]
    unavailable: tuple[dict[str, str], ...]
    manifest_digest: str
    coverage_receipt: StructuralCoverageReceipt


def build_query_manifest(
    *,
    release: OntologyRelease,
    principal_role: CeilingRole,
    purposes: Sequence[str],
    principal_scope_digest: str,
    object_types: Sequence[OntologyObjectType] = (),
    link_types: Sequence[OntologyLinkType] = (),
    interfaces: Sequence[OntologyInterfaceType] = (),
    action_types: Sequence[OntologyActionType] = (),
    functions: Sequence[OntologyFunctionType] = (),
) -> QueryManifest:
    """Project every readable declaration or one typed unavailable record.

    The builder exposes schemas and safe query metadata only. Runtime instances,
    provider bindings, function callbacks, and mutation handlers never enter the
    manifest.
    """

    normalized_purposes = tuple(sorted(set(purposes)))
    declarations = {(item.kind, item.name): item for item in release.declarations}
    supplied: dict[tuple[OntologyDeclarationKind, str], object] = {}
    supplied.update({(OntologyDeclarationKind.OBJECT, item.name): item for item in object_types})
    supplied.update({(OntologyDeclarationKind.LINK, item.name): item for item in link_types})
    supplied.update({(OntologyDeclarationKind.INTERFACE, item.name): item for item in interfaces})
    supplied.update({(OntologyDeclarationKind.ACTION, item.name): item for item in action_types})
    supplied.update({(OntologyDeclarationKind.FUNCTION, item.name): item for item in functions})
    orphaned = sorted(set(supplied) - set(declarations), key=lambda item: (item[0].value, item[1]))
    if orphaned:
        rendered = ", ".join(f"{kind.value}:{name}" for kind, name in orphaned[:10])
        raise ValueError(f"query manifest declarations are absent from the release: {rendered}")
    missing = sorted(set(declarations) - set(supplied), key=lambda item: (item[0].value, item[1]))
    if missing:
        rendered = ", ".join(f"{kind.value}:{name}" for kind, name in missing[:10])
        raise ValueError(f"query manifest release declarations are unavailable: {rendered}")

    descriptors: list[dict[str, Any]] = []
    unavailable: list[dict[str, str]] = []
    readable_count = 0
    for key, declaration_ref in sorted(
        declarations.items(), key=lambda item: (item[0][0].value, item[0][1])
    ):
        declaration = supplied[key]
        if isinstance(declaration, OntologyFunctionType) and not _function_readable(
            declaration,
            role=principal_role,
            purposes=normalized_purposes,
        ):
            continue
        readable_count += 1
        descriptor, reason = _descriptor(
            declaration,
            declaration_ref.declaration_digest,
            role=principal_role,
            purposes=normalized_purposes,
        )
        if reason is None:
            descriptors.append(descriptor)
        else:
            unavailable.append(
                {
                    "declaration_id": f"{key[0].value}:{key[1]}",
                    "reason": reason,
                }
            )

    descriptors_tuple = tuple(descriptors)
    unavailable_tuple = tuple(unavailable)
    manifest_body = {
        "release_digest": release.digest,
        "principal_role": principal_role.value,
        "purposes": normalized_purposes,
        "descriptors": descriptors_tuple,
        "unavailable": unavailable_tuple,
        "mutation_authority": False,
    }
    manifest_digest = _manifest_digest(manifest_body)
    unavailable_ids = tuple(item["declaration_id"] for item in unavailable_tuple)
    receipt_body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": release.digest,
        "principal_scope_digest": principal_scope_digest,
        "readable_declaration_count": readable_count,
        "descriptor_count": len(descriptors_tuple),
        "unavailable_declaration_ids": unavailable_ids,
        "manifest_digest": manifest_digest,
        "complete": len(descriptors_tuple) + len(unavailable_ids) == readable_count,
    }
    coverage_receipt = StructuralCoverageReceipt(
        ontology_release_digest=release.digest,
        principal_scope_digest=principal_scope_digest,
        readable_declaration_count=readable_count,
        descriptor_count=len(descriptors_tuple),
        unavailable_declaration_ids=unavailable_ids,
        manifest_digest=manifest_digest,
        complete=len(descriptors_tuple) + len(unavailable_ids) == readable_count,
        receipt_digest=content_digest(receipt_body),
    )
    return QueryManifest(
        release_digest=release.digest,
        principal_role=principal_role,
        purposes=normalized_purposes,
        descriptors=descriptors_tuple,
        unavailable=unavailable_tuple,
        manifest_digest=manifest_digest,
        coverage_receipt=coverage_receipt,
    )


def _function_readable(
    declaration: OntologyFunctionType,
    *,
    role: CeilingRole,
    purposes: tuple[str, ...],
) -> bool:
    if CEILING_ROLE_RANK[role] < CEILING_ROLE_RANK[declaration.required_role]:
        return False
    return not declaration.purpose_bindings or bool(
        set(declaration.purpose_bindings).intersection(purposes)
    )


def _descriptor(
    declaration: object,
    declaration_digest: str,
    *,
    role: CeilingRole,
    purposes: tuple[str, ...],
) -> tuple[dict[str, Any], str | None]:
    if isinstance(declaration, OntologyObjectType):
        return (
            {
                "kind": "object",
                "name": declaration.name,
                "version": str(declaration.version),
                "declaration_digest": declaration_digest,
                "key": declaration.key,
                "properties": {
                    name: {
                        "type": prop.type.value,
                        "required": prop.required,
                        "access_scope": prop.access_scope.value,
                        "purpose_binding": sorted(prop.purpose_binding),
                    }
                    for name, prop in sorted(declaration.properties.items())
                    if _property_readable(prop.access_scope, prop.purpose_binding, role, purposes)
                },
            },
            None,
        )
    if isinstance(declaration, OntologyInterfaceType):
        return (
            {
                "kind": "interface",
                "name": declaration.name,
                "version": str(declaration.version),
                "declaration_digest": declaration_digest,
                "properties": [
                    name
                    for name, prop in sorted(declaration.properties.items())
                    if _property_readable(
                        prop.access_scope,
                        prop.purpose_binding,
                        role,
                        purposes,
                    )
                ],
                "required_links": sorted(declaration.required_links),
                "supported_actions": sorted(declaration.supported_actions),
                "extends": sorted(declaration.extends),
            },
            None,
        )
    if isinstance(declaration, OntologyLinkType):
        return (
            {
                "kind": "link",
                "name": declaration.name,
                "version": str(declaration.version),
                "declaration_digest": declaration_digest,
                "from_type": declaration.from_type,
                "to_type": declaration.to_type,
                "cardinality": declaration.cardinality.value,
                "stored_direction": "from_to",
                "query_sides": {
                    "from": {
                        "query_id": f"{declaration.name}.outgoing",
                        "endpoint_type": declaration.from_type,
                        "direction": "outgoing",
                    },
                    "to": {
                        "query_id": f"{declaration.name}.incoming",
                        "endpoint_type": declaration.to_type,
                        "direction": "incoming",
                    },
                },
                "is_transitive": declaration.is_transitive,
                "is_causal": declaration.is_causal,
                "temporal_order": declaration.temporal_order,
            },
            None,
        )
    if isinstance(declaration, OntologyFunctionType):
        return (
            {
                "kind": "function",
                "name": declaration.name,
                "version": str(declaration.version),
                "declaration_digest": declaration_digest,
                "function_kind": declaration.kind.value,
                "input_schema": declaration.input_schema,
                "output_schema": declaration.output_schema,
                "read_sets": sorted(declaration.read_sets),
                "required_role": declaration.required_role.value,
                "purpose_bindings": sorted(declaration.purpose_bindings),
                "execution_class": declaration.execution_class.value,
                "network_allowed": declaration.network_allowed,
                "credentials_allowed": declaration.credentials_allowed,
                "execution_authority": False,
            },
            None,
        )
    if isinstance(declaration, OntologyActionType):
        return (
            {
                "kind": "action",
                "name": declaration.name,
                "version": str(declaration.version),
                "declaration_digest": declaration_digest,
                "operation": declaration.operation.value,
                "argument_schema": declaration.argument_schema,
                "draft_only": True,
                "execution_authority": False,
            },
            None,
        )
    raise TypeError(f"unsupported query manifest declaration {type(declaration).__name__}")


def _property_readable(
    access_scope: CeilingRole,
    purpose_binding: Sequence[str],
    role: CeilingRole,
    purposes: tuple[str, ...],
) -> bool:
    if CEILING_ROLE_RANK[role] < CEILING_ROLE_RANK[access_scope]:
        return False
    return not purpose_binding or bool(set(purpose_binding).intersection(purposes))


def _manifest_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    if len(encoded) > _MAX_MANIFEST_BYTES:
        raise ValueError(f"query manifest exceeds {_MAX_MANIFEST_BYTES} bytes")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = ["QueryManifest", "build_query_manifest"]
