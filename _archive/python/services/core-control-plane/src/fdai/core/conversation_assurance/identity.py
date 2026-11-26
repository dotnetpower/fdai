"""Stable privacy-preserving identities for conversation assurance."""

from __future__ import annotations

import hashlib


def assurance_principal_scope(principal_id: str) -> str:
    if not principal_id.strip():
        raise ValueError("assurance principal_id MUST be non-empty")
    digest = hashlib.sha256(principal_id.casefold().encode()).hexdigest()
    return f"principal:{digest}"


__all__ = ["assurance_principal_scope"]
