"""Canonical provenance verification for ontology declaration catalogs."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel


def ontology_content_hash(declaration: BaseModel) -> str:
    """Hash the normalized declaration while excluding its provenance envelope."""

    payload = declaration.model_dump(
        mode="json",
        exclude={"provenance"},
        exclude_none=True,
    )
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


__all__ = ["ontology_content_hash", "ontology_provenance_error"]
