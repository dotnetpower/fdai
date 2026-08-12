"""Canonical content digest helpers for immutable catalog records."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel


def canonical_catalog_digest(
    record: BaseModel,
    *,
    exclude: frozenset[str] = frozenset({"content_digest", "provenance"}),
) -> str:
    """Hash one record without self-referential digest and provenance fields."""

    payload = record.model_dump(mode="json", exclude=exclude, exclude_none=True)
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


__all__ = ["canonical_catalog_digest"]
