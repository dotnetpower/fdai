"""backfill the exact historical ontology release manifest

Revision ID: 20260817_0085
Revises: 20260814_0084
Create Date: 2026-08-17 00:00:00+00:00
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from alembic import op
from sqlalchemy import text

revision: str = "20260817_0085"
down_revision: str | None = "20260814_0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BASE_RELEASE_DIGEST = "sha256:596873529ea6b479363fa34b07c326db02117726ac4d790f42a9abc707c6939d"
_SCHEMA_VERSION = "1.0.0"
_EXPECTED_DIGEST = "sha256:13f0dbf8ca4420df10aa730e2e1701ad2f22fa57da059b2a8181e4a9073ae349"
_EXPECTED_BYTE_LENGTH = 27670
_EXPECTED_DECLARATION_COUNTS = {"link": 103, "object": 73}
_REMOVED_IDENTITIES = frozenset(
    {
        ("link", "attached_to", "1.1.0"),
        ("link", "considers", "1.0.0"),
        ("link", "executed_as", "1.0.0"),
        ("link", "expects", "1.0.0"),
        ("link", "hypothesis_informs_expected_effect", "1.0.0"),
        ("link", "resource_classified_as", "1.0.0"),
        ("link", "resulted_in", "1.0.0"),
        ("object", "PolicyArtifact", "1.1.0"),
    }
)
_HISTORICAL_DECLARATIONS = (
    {
        "kind": "link",
        "name": "attached_to",
        "version": "1.0.0",
        "declaration_digest": (
            "sha256:7c5902d087e76c6eaa176837ab05d16d36067c717f46e33a928b356f9cfab2a9"
        ),
    },
    {
        "kind": "object",
        "name": "PolicyArtifact",
        "version": "1.0.0",
        "declaration_digest": (
            "sha256:5e81d6932e58ace71f8d9a695df967d7e5f3f553fa83bf6de95fac5f5c4bde16"
        ),
    },
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


def _declaration_identity(declaration: Mapping[str, object]) -> tuple[str, str, str]:
    identity = tuple(declaration.get(key) for key in ("kind", "name", "version"))
    if not all(isinstance(value, str) and value for value in identity):
        raise ValueError("Ontology release declaration identity is invalid")
    return identity  # type: ignore[return-value]


def _build_historical_manifest(base_manifest: Mapping[str, object]) -> bytes:
    base_declarations = base_manifest.get("declarations")
    if not isinstance(base_declarations, list):
        raise ValueError("Base ontology release declarations must be a list")
    if base_manifest.get("digest") != _BASE_RELEASE_DIGEST:
        raise ValueError("Base ontology release digest mismatch")
    if base_manifest.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("Base ontology release schema version mismatch")
    if _digest(base_declarations) != _BASE_RELEASE_DIGEST:
        raise ValueError("Base ontology release declarations do not match their digest")

    declarations: list[dict[str, object]] = []
    removed: set[tuple[str, str, str]] = set()
    for declaration in base_declarations:
        if not isinstance(declaration, dict):
            raise ValueError("Base ontology release declaration must be a JSON object")
        identity = _declaration_identity(declaration)
        if identity in _REMOVED_IDENTITIES:
            removed.add(identity)
            continue
        declarations.append(dict(declaration))
    if removed != _REMOVED_IDENTITIES:
        raise ValueError("Base ontology release does not contain the exact historical delta")

    declarations.extend(dict(item) for item in _HISTORICAL_DECLARATIONS)
    declarations.sort(key=_declaration_identity)
    if _digest(declarations) != _EXPECTED_DIGEST:
        raise ValueError("Historical ontology release declarations do not match their digest")
    counts = Counter(str(declaration["kind"]) for declaration in declarations)
    if dict(sorted(counts.items())) != _EXPECTED_DECLARATION_COUNTS:
        raise ValueError("Historical ontology release declaration counts mismatch")

    raw = json.dumps(
        {
            "schema_version": _SCHEMA_VERSION,
            "digest": _EXPECTED_DIGEST,
            "declarations": declarations,
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode()
    if len(raw) != _EXPECTED_BYTE_LENGTH:
        raise ValueError(
            "Historical ontology release length mismatch: "
            f"expected {_EXPECTED_BYTE_LENGTH}, got {len(raw)}"
        )
    return raw


def upgrade() -> None:
    connection = op.get_bind()
    base_manifest = connection.execute(
        text("SELECT manifest FROM ontology_release WHERE digest = :digest"),
        {"digest": _BASE_RELEASE_DIGEST},
    ).scalar_one()
    if not isinstance(base_manifest, dict):
        raise ValueError("Base ontology release manifest must be a JSON object")
    manifest = _build_historical_manifest(base_manifest).decode("utf-8")
    connection.execute(
        text(
            """
            INSERT INTO ontology_release (digest, manifest)
            VALUES (:digest, CAST(:manifest AS JSONB))
            ON CONFLICT (digest) DO NOTHING
            """
        ),
        {"digest": _EXPECTED_DIGEST, "manifest": manifest},
    )


def downgrade() -> None:
    op.execute(
        text(
            """
            DELETE FROM ontology_release AS release
            WHERE release.digest = :digest
              AND NOT EXISTS (
                  SELECT 1 FROM ontology_resource
                  WHERE catalog_digest = release.digest
              )
              AND NOT EXISTS (
                  SELECT 1 FROM ontology_link
                  WHERE catalog_digest = release.digest
              )
            """
        ).bindparams(digest=_EXPECTED_DIGEST)
    )
