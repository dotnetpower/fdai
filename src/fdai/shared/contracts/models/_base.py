"""Base classes and semver / idempotency-key type aliases shared by every
domain-specific contract model.

Kept in a private submodule so the domain files (:mod:`.event`,
:mod:`.incident`, ...) all import from one place and the model-config /
strict-mode contract is defined exactly once.

Public alias
------------

The base class is exposed under two names:

- :class:`ContractBase` - the **public** name a fork or a downstream
  extension should subclass when adding a bespoke contract model.
- :class:`_Base` - the historical name kept as an alias for backwards
  compatibility with existing imports inside this package. Prefer
  :class:`ContractBase` in new code.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Aliases mirroring the JSON Schema pattern for semver strings.
SemVer = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$", min_length=5)]
IdempotencyKey = Annotated[str, Field(min_length=1, max_length=512)]


class ContractBase(BaseModel):
    """Public base for every FDAI contract model.

    Enforces the four invariants every contract carries:

    - ``extra="forbid"`` - unknown fields are a validation error, so a
      drifted payload cannot silently succeed.
    - ``frozen=True`` - instances are immutable after construction, so a
      contract cannot be mutated in flight.
    - ``str_strip_whitespace=True`` - leading/trailing whitespace on any
      string field is stripped at parse time.
    - ``validate_default=True`` - default values are validated the same
      way as user-supplied ones.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


# Historical alias - kept so existing imports (`from ._base import _Base`)
# continue to work while new code migrates to :class:`ContractBase`.
_Base = ContractBase


_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"


class OntologyDeclarationKind(StrEnum):
    OBJECT = "object"
    LINK = "link"
    ACTION = "action"
    INTERFACE = "interface"
    FUNCTION = "function"


class OntologyDeclarationRef(ContractBase):
    kind: OntologyDeclarationKind
    name: Annotated[str, Field(min_length=1)]
    version: SemVer
    declaration_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]


class OntologyTypeRef(ContractBase):
    kind: OntologyDeclarationKind
    name: Annotated[str, Field(min_length=1)]
    version: SemVer
    catalog_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]


class OntologyReleaseRef(ContractBase):
    """Compact exact identity for cross-service ontology-aware records."""

    schema_version: SemVer = "1.0.0"
    digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]


class OntologyRelease(ContractBase):
    schema_version: SemVer = "1.0.0"
    digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    declarations: tuple[OntologyDeclarationRef, ...]

    @model_validator(mode="after")
    def _content_is_canonical(self) -> OntologyRelease:
        from fdai.shared.ontology.release import validate_ontology_release

        validate_ontology_release(self)
        return self

    def ref(self) -> OntologyReleaseRef:
        """Return the compact exact identity used on semantic wire records."""

        return OntologyReleaseRef(
            schema_version=self.schema_version,
            digest=self.digest,
        )

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
    "ContractBase",
    "IdempotencyKey",
    "OntologyDeclarationKind",
    "OntologyDeclarationRef",
    "OntologyRelease",
    "OntologyReleaseRef",
    "OntologyTypeRef",
    "SemVer",
    "_Base",
]
