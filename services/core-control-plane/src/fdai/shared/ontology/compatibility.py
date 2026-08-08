"""Fail-closed compatibility gate for ontology-aware generation activation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.shared.contracts.compatibility import check_schema_compatibility
from fdai.shared.contracts.models import OntologyDeclarationKind, OntologyRelease

type OntologySchemaIdentity = tuple[OntologyDeclarationKind, str]
type OntologySchemaCatalog = Mapping[OntologySchemaIdentity, Mapping[str, Any]]


class OntologyGenerationCompatibilityError(ValueError):
    """The candidate generation cannot safely replace the prior ontology release."""


@dataclass(frozen=True, slots=True)
class OntologyGenerationCompatibilityReceipt:
    """Immutable proof that one candidate generation passed the N/N-1 gate."""

    previous_release_digest: str
    candidate_release_digest: str
    checked_declarations: tuple[str, ...]
    added_declarations: tuple[str, ...]


def require_ontology_generation_compatibility(
    *,
    previous_release: OntologyRelease,
    candidate_release: OntologyRelease,
    previous_schemas: OntologySchemaCatalog,
    candidate_schemas: OntologySchemaCatalog,
    generation_release_digest: str,
) -> OntologyGenerationCompatibilityReceipt:
    """Validate exact release pinning and additive N/N-1 schema evolution.

    Callers must invoke this pure gate before provider access or generation
    activation. Missing declarations, missing schema evidence, and breaking
    retained-declaration changes fail closed.
    """

    if generation_release_digest != candidate_release.digest:
        raise OntologyGenerationCompatibilityError(
            "ontology generation release digest does not match the candidate release"
        )

    previous = _declarations(previous_release)
    candidate = _declarations(candidate_release)
    _require_exact_schema_coverage("previous", previous, previous_schemas)
    _require_exact_schema_coverage("candidate", candidate, candidate_schemas)

    removed = previous.keys() - candidate.keys()
    if removed:
        raise OntologyGenerationCompatibilityError(
            "ontology generation removes declaration "
            f"{_display_identity(min(removed, key=_identity_sort_key))}"
        )

    checked: list[str] = []
    for identity in sorted(previous, key=_identity_sort_key):
        report = check_schema_compatibility(
            previous_schemas[identity],
            candidate_schemas[identity],
        )
        if not report.is_compatible:
            change = report.breaking_changes[0]
            raise OntologyGenerationCompatibilityError(
                "ontology generation has a breaking schema change for "
                f"{_display_identity(identity)} at {change.path!r}: {change.detail}"
            )
        checked.append(_display_identity(identity))

    added = tuple(
        _display_identity(identity)
        for identity in sorted(candidate.keys() - previous.keys(), key=_identity_sort_key)
    )
    return OntologyGenerationCompatibilityReceipt(
        previous_release_digest=previous_release.digest,
        candidate_release_digest=candidate_release.digest,
        checked_declarations=tuple(checked),
        added_declarations=added,
    )


def _declarations(release: OntologyRelease) -> dict[OntologySchemaIdentity, str]:
    return {(item.kind, item.name): item.version for item in release.declarations}


def _require_exact_schema_coverage(
    label: str,
    declarations: Mapping[OntologySchemaIdentity, str],
    schemas: OntologySchemaCatalog,
) -> None:
    missing = declarations.keys() - schemas.keys()
    if missing:
        raise OntologyGenerationCompatibilityError(
            f"{label} ontology release schema is missing "
            f"{_display_identity(min(missing, key=_identity_sort_key))}"
        )
    extra = schemas.keys() - declarations.keys()
    if extra:
        raise OntologyGenerationCompatibilityError(
            f"{label} ontology release schema has unknown "
            f"{_display_identity(min(extra, key=_identity_sort_key))}"
        )


def _identity_sort_key(identity: OntologySchemaIdentity) -> tuple[str, str]:
    return identity[0].value, identity[1]


def _display_identity(identity: OntologySchemaIdentity) -> str:
    return f"{identity[0].value}:{identity[1]}"


__all__ = [
    "OntologyGenerationCompatibilityError",
    "OntologyGenerationCompatibilityReceipt",
    "OntologySchemaCatalog",
    "OntologySchemaIdentity",
    "require_ontology_generation_compatibility",
]
