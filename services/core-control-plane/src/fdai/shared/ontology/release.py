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
        declaration_digest=_digest(declaration.model_dump(mode="json", exclude_none=True)),
    )


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
