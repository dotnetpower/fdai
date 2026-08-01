"""Exact ontology declaration and release identities for replay."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from ._base import SemVer, _Base

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"


class OntologyDeclarationKind(StrEnum):
    OBJECT = "object"
    LINK = "link"
    ACTION = "action"
    INTERFACE = "interface"
    FUNCTION = "function"


class OntologyDeclarationRef(_Base):
    kind: OntologyDeclarationKind
    name: Annotated[str, Field(min_length=1)]
    version: SemVer
    declaration_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]


class OntologyTypeRef(_Base):
    kind: OntologyDeclarationKind
    name: Annotated[str, Field(min_length=1)]
    version: SemVer
    catalog_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]


class OntologyRelease(_Base):
    schema_version: SemVer = "1.0.0"
    digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    declarations: tuple[OntologyDeclarationRef, ...]

    def type_ref(self, kind: OntologyDeclarationKind, name: str) -> OntologyTypeRef:
        for declaration in self.declarations:
            if declaration.kind is kind and declaration.name == name:
                return OntologyTypeRef(
                    kind=kind,
                    name=name,
                    version=declaration.version,
                    catalog_digest=self.digest,
                )
        raise KeyError(f"ontology release has no {kind.value} declaration {name!r}")


__all__ = [
    "OntologyDeclarationKind",
    "OntologyDeclarationRef",
    "OntologyRelease",
    "OntologyTypeRef",
]
