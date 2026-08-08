"""Versioned immutable profiles for bounded ontology queries."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from fdai.shared.contracts.models import (
    ContractBase,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyTypeRef,
    SemVer,
)

from .functions import ontology_function_digest
from .models import ObjectSetDefinition


class QueryProfile(ContractBase):
    """Bind one exact query function to one reviewed bounded ObjectSet template."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")]
    version: SemVer
    function_type: OntologyFunctionType
    function_ref: OntologyTypeRef
    object_set_template: ObjectSetDefinition
    purpose: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
    output_kind: Literal["object_set"] = "object_set"

    @property
    def profile_ref(self) -> str:
        """Return the stable logical identity for this profile version."""

        return f"query-profile:{self.name}@{self.version}"

    @property
    def profile_digest(self) -> str:
        """Return the canonical digest of the complete reviewed profile content."""

        return ontology_function_digest(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def _selection_is_consistent(self) -> QueryProfile:
        if self.function_type.kind is not OntologyFunctionKind.QUERY:
            raise ValueError("query profile function_type MUST be query")
        if self.function_ref.kind is not OntologyDeclarationKind.FUNCTION:
            raise ValueError("query profile function_ref MUST reference a function")
        if (
            self.function_ref.name != self.function_type.name
            or self.function_ref.version != self.function_type.version
        ):
            raise ValueError("query profile function_ref MUST match function_type")
        if self.object_set_template.purpose != self.purpose:
            raise ValueError("query profile purpose MUST match ObjectSet template purpose")
        if (
            self.function_type.purpose_bindings
            and self.purpose not in self.function_type.purpose_bindings
        ):
            raise ValueError("query profile purpose is not allowed by function_type")
        return self


__all__ = ["QueryProfile"]
