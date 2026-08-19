"""Read-only declaration detail and dependent queries over one exact release."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fdai.shared.contracts.models import (
    CEILING_ROLE_RANK,
    CeilingRole,
    LogicExecutionClass,
    OntologyActionType,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyInterfaceImplementation,
    OntologyInterfaceType,
    OntologyLinkType,
    OntologyObjectType,
    OntologyRelease,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext

ONTOLOGY_DECLARATION_FUNCTION_NAME = "query.ontology_declaration"
ONTOLOGY_DECLARATION_PURPOSE = "operations-review"
_MAX_ROWS = 100
_KINDS = ("action", "link", "object")
_SECTIONS = ("detail", "dependents")


def ontology_declaration_function_type() -> OntologyFunctionType:
    """Return the no-authority declaration projection FunctionType."""

    return OntologyFunctionType(
        name=ONTOLOGY_DECLARATION_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "name", "section", "limit"],
            "properties": {
                "kind": {"enum": list(_KINDS)},
                "name": {"type": "string", "minLength": 1, "maxLength": 128},
                "section": {"enum": list(_SECTIONS)},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_ROWS},
            },
        },
        output_schema=_query_table_schema(),
        read_sets=[],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[ONTOLOGY_DECLARATION_PURPOSE],
        timeout_seconds=1,
        cpu_millis=100,
        memory_bytes=33_554_432,
        max_output_bytes=524_288,
        network_allowed=False,
        credentials_allowed=False,
    )


def ontology_declaration_function(
    ontology_release: OntologyRelease,
    *,
    object_types: Sequence[OntologyObjectType],
    link_types: Sequence[OntologyLinkType],
    action_types: Sequence[OntologyActionType],
    interface_types: Sequence[OntologyInterfaceType],
    interface_implementations: Sequence[OntologyInterfaceImplementation],
) -> ContextualOntologyFunction:
    """Bind exact catalog declarations without importing delivery projections."""

    objects = {item.name: item for item in object_types}
    links = {item.name: item for item in link_types}
    actions = {item.name: item for item in action_types}
    interfaces = {item.name: item for item in interface_types}
    implementations = tuple(interface_implementations)
    for kind, declarations in (
        (OntologyDeclarationKind.OBJECT, objects),
        (OntologyDeclarationKind.LINK, links),
        (OntologyDeclarationKind.ACTION, actions),
        (OntologyDeclarationKind.INTERFACE, interfaces),
    ):
        for name in declarations:
            ontology_release.type_ref(kind, name)
    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        ONTOLOGY_DECLARATION_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != (ONTOLOGY_DECLARATION_PURPOSE,):
            raise PermissionError("ontology declaration purpose does not match invocation context")
        kind = str(arguments["kind"])
        name = str(arguments["name"])
        section = str(arguments["section"])
        limit = int(arguments["limit"])
        declaration = _declaration(kind, name, objects=objects, links=links, actions=actions)
        if section == "detail":
            values = _detail_values(
                kind,
                declaration,
                ontology_release=ontology_release,
                context=invocation_context,
            )
            rows = [{"row_id": f"{kind}:{name}", "values": values}]
            complete = True
        else:
            dependents = _dependents(
                kind,
                name,
                links=links,
                actions=actions,
                interfaces=interfaces,
                implementations=implementations,
            )
            selected = dependents[:limit]
            rows = [
                {
                    "row_id": f"{item['dependent_kind']}:{item['dependent_name']}",
                    "values": {
                        "ontology_release_digest": ontology_release.digest,
                        "declaration_kind": kind,
                        "declaration_name": name,
                        "section": section,
                        **item,
                        "execution_authority": False,
                        "mutation_authority": False,
                    },
                }
                for item in selected
            ]
            complete = len(selected) == len(dependents)
        return {
            "rows": rows,
            "complete": complete,
            "truncation_reason": None if complete else "result_limit",
        }

    return evaluate


def _declaration(
    kind: str,
    name: str,
    *,
    objects: Mapping[str, OntologyObjectType],
    links: Mapping[str, OntologyLinkType],
    actions: Mapping[str, OntologyActionType],
) -> OntologyObjectType | OntologyLinkType | OntologyActionType:
    declaration: OntologyObjectType | OntologyLinkType | OntologyActionType
    try:
        if kind == "object":
            declaration = objects[name]
        elif kind == "link":
            declaration = links[name]
        else:
            declaration = actions[name]
    except KeyError as error:
        raise LookupError(f"unknown {kind} declaration: {name}") from error
    return declaration


def _detail_values(
    kind: str,
    declaration: OntologyObjectType | OntologyLinkType | OntologyActionType,
    *,
    ontology_release: OntologyRelease,
    context: FunctionInvocationContext,
) -> dict[str, object]:
    detail = declaration.model_dump(mode="json", exclude_none=True)
    redaction_reasons: set[str] = set()
    if isinstance(declaration, OntologyObjectType):
        visible_properties: dict[str, object] = {}
        for name, prop in sorted(declaration.properties.items()):
            role_allowed = (
                CEILING_ROLE_RANK[context.caller_role] >= CEILING_ROLE_RANK[prop.access_scope]
            )
            purpose_allowed = not prop.purpose_binding or bool(
                set(context.purposes).intersection(prop.purpose_binding)
            )
            if role_allowed and purpose_allowed:
                visible_properties[name] = prop.model_dump(mode="json")
            else:
                if not role_allowed:
                    redaction_reasons.add("role")
                if not purpose_allowed:
                    redaction_reasons.add("purpose")
        detail["properties"] = visible_properties
    return {
        "ontology_release_digest": ontology_release.digest,
        "declaration_kind": kind,
        "declaration_name": declaration.name,
        "section": "detail",
        "declaration": detail,
        "redaction_reasons": sorted(redaction_reasons),
        "execution_authority": False,
        "mutation_authority": False,
    }


def _dependents(
    kind: str,
    name: str,
    *,
    links: Mapping[str, OntologyLinkType],
    actions: Mapping[str, OntologyActionType],
    interfaces: Mapping[str, OntologyInterfaceType],
    implementations: Sequence[OntologyInterfaceImplementation],
) -> tuple[dict[str, str], ...]:
    if kind != "object":
        return ()
    rows: list[dict[str, str]] = [
        {
            "dependent_kind": "link",
            "dependent_name": item.name,
            "relationship": "references_object_type",
        }
        for item in links.values()
        if name in {item.from_type, item.to_type}
    ]
    implemented = {
        interface
        for item in implementations
        if item.object_type == name
        for interface in item.interfaces
    }
    rows.extend(
        {
            "dependent_kind": "interface",
            "dependent_name": interface,
            "relationship": "implemented_by_object_type",
        }
        for interface in implemented
        if interface in interfaces
    )
    rows.extend(
        {
            "dependent_kind": "action",
            "dependent_name": action.name,
            "relationship": "targets_object_type",
        }
        for action in actions.values()
        if action.semantic is not None
        and action.semantic.target.type_ref.kind is OntologyDeclarationKind.OBJECT
        and action.semantic.target.type_ref.name == name
    )
    return tuple(
        sorted(
            rows,
            key=lambda item: (
                item["dependent_kind"],
                item["dependent_name"],
                item["relationship"],
            ),
        )
    )


def _query_table_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["rows", "complete", "truncation_reason"],
        "properties": {
            "rows": {
                "type": "array",
                "maxItems": _MAX_ROWS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["row_id", "values"],
                    "properties": {
                        "row_id": {"type": "string", "minLength": 1, "maxLength": 512},
                        "values": {
                            "type": "object",
                            "required": [
                                "ontology_release_digest",
                                "declaration_kind",
                                "declaration_name",
                                "section",
                                "execution_authority",
                                "mutation_authority",
                            ],
                            "properties": {
                                "ontology_release_digest": {
                                    "type": "string",
                                    "pattern": "^sha256:[a-f0-9]{64}$",
                                },
                                "declaration_kind": {"enum": list(_KINDS)},
                                "declaration_name": {"type": "string"},
                                "section": {"enum": list(_SECTIONS)},
                                "execution_authority": {"const": False},
                                "mutation_authority": {"const": False},
                            },
                        },
                    },
                },
            },
            "complete": {"type": "boolean"},
            "truncation_reason": {
                "type": ["string", "null"],
                "enum": ["result_limit", None],
            },
        },
    }


__all__ = [
    "ONTOLOGY_DECLARATION_FUNCTION_NAME",
    "ONTOLOGY_DECLARATION_PURPOSE",
    "ontology_declaration_function",
    "ontology_declaration_function_type",
]
