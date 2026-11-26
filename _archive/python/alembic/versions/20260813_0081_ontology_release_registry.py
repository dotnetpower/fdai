"""persist exact ontology release manifests

Revision ID: 20260813_0081
Revises: 20260813_0080
Create Date: 2026-08-13 00:00:01+00:00
"""

from __future__ import annotations

import base64
import json
import zlib
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

_EXPECTED_DIGEST = "sha256:596873529ea6b479363fa34b07c326db02117726ac4d790f42a9abc707c6939d"
_EXPECTED_BYTE_LENGTH = 28598
_RELEASE_SEED_B64 = (
    "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"
    "Iyk="
)

revision: str = "20260813_0081"
down_revision: str | None = "20260813_0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _decode_release_seed() -> bytes:
    try:
        compressed = base64.b64decode(_RELEASE_SEED_B64, validate=True)
    except ValueError as exc:
        raise ValueError("Ontology release seed is not valid base64") from exc
    try:
        raw = zlib.decompress(compressed)
    except zlib.error as exc:
        raise ValueError("Ontology release seed is not valid zlib data") from exc
    if len(raw) != _EXPECTED_BYTE_LENGTH:
        raise ValueError(
            "Ontology release seed length mismatch: "
            f"expected {_EXPECTED_BYTE_LENGTH}, got {len(raw)}"
        )
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Ontology release seed is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Ontology release seed must be a JSON object")
    if manifest.get("digest") != _EXPECTED_DIGEST:
        raise ValueError("Ontology release seed digest mismatch")
    if not isinstance(manifest.get("declarations"), list):
        raise ValueError("Ontology release seed declarations must be a list")
    return raw


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ontology_release (
            digest TEXT PRIMARY KEY,
            manifest JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_ontology_release_digest
                CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
            CONSTRAINT ck_ontology_release_manifest_object
                CHECK (jsonb_typeof(manifest) = 'object'),
            CONSTRAINT ck_ontology_release_manifest_digest
                CHECK (manifest ->> 'digest' = digest),
            CONSTRAINT ck_ontology_release_declarations_array
                CHECK (jsonb_typeof(manifest -> 'declarations') = 'array')
        );
        """
    )
    manifest = _decode_release_seed().decode("utf-8")
    # This transitional seed is exact migration evidence, not inferred provenance.
    op.get_bind().execute(
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
    op.execute("DROP TABLE ontology_release")
