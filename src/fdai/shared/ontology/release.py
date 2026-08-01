"""Canonical ontology release construction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from fdai.shared.contracts.models.ontology import (
    OntologyActionType,
    OntologyLinkType,
    OntologyObjectType,
)
from fdai.shared.contracts.models.ontology_identity import (
    OntologyDeclarationKind,
    OntologyDeclarationRef,
    OntologyRelease,
)


def build_ontology_release(
    *,
    object_types: Sequence[OntologyObjectType] = (),
    link_types: Sequence[OntologyLinkType] = (),
    action_types: Sequence[OntologyActionType] = (),
) -> OntologyRelease:
    """Build one deterministic release over the supplied declarations."""

    declarations = tuple(
        sorted(
            (
                *(_declaration_ref(OntologyDeclarationKind.OBJECT, item) for item in object_types),
                *(_declaration_ref(OntologyDeclarationKind.LINK, item) for item in link_types),
                *(_declaration_ref(OntologyDeclarationKind.ACTION, item) for item in action_types),
            ),
            key=lambda item: (item.kind.value, item.name, item.version),
        )
    )
    identities = {(item.kind, item.name) for item in declarations}
    if len(identities) != len(declarations):
        raise ValueError("ontology release declaration identities MUST be unique")
    return OntologyRelease(
        digest=_digest([item.model_dump(mode="json") for item in declarations]),
        declarations=declarations,
    )


def _declaration_ref(
    kind: OntologyDeclarationKind,
    declaration: OntologyObjectType | OntologyLinkType | OntologyActionType,
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
