"""Canonical provenance verification for ontology declaration catalogs."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyInterfaceType,
    OntologyLinkType,
    OntologyObjectType,
)


def ontology_content_hash(declaration: BaseModel) -> str:
    """Hash the normalized declaration while excluding its provenance envelope."""

    payload = declaration.model_dump(
        mode="json",
        exclude={"provenance"},
        exclude_none=True,
    )
    # Additive LinkType semantics must not reinterpret historical declarations
    # that were hashed before these optional fields existed.
    if isinstance(declaration, OntologyLinkType):
        if payload.get("semantic_traits") == []:
            payload.pop("semantic_traits")
        if payload.get("forward_role") is None:
            payload.pop("forward_role", None)
        if payload.get("reverse_role") is None:
            payload.pop("reverse_role", None)
    if isinstance(declaration, OntologyObjectType):
        if payload.get("query_terms") == []:
            payload.pop("query_terms")
    if isinstance(declaration, OntologyObjectType | OntologyInterfaceType):
        _strip_empty_property_terms(payload)
    if (
        isinstance(declaration, OntologyActionType)
        and payload.get("required_evidence_semantic_refs") == []
    ):
        payload.pop("required_evidence_semantic_refs")
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def ontology_provenance_error(declaration: BaseModel) -> str | None:
    provenance = getattr(declaration, "provenance", None)
    if provenance is None:
        return "catalog declaration MUST include provenance"
    expected = ontology_content_hash(declaration)
    if provenance.content_hash != expected:
        return (
            f"provenance.content_hash mismatch: expected {expected}, got {provenance.content_hash}"
        )
    return None


def _strip_empty_property_terms(payload: dict[str, object]) -> None:
    properties = payload.get("properties")
    if not isinstance(properties, dict):
        return
    for property_payload in properties.values():
        if not isinstance(property_payload, dict):
            continue
        if property_payload.get("query_terms") == []:
            property_payload.pop("query_terms")
        if property_payload.get("value_query_terms") == {}:
            property_payload.pop("value_query_terms")


__all__ = ["ontology_content_hash", "ontology_provenance_error"]
