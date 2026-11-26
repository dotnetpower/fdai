"""operator_memory: append-only store for Human Override notes

Revision ID: 20260706_0006
Revises: 20260706_0005
Create Date: 2026-07-06 00:00:00

Backs
:class:`~fdai.core.operator_memory.store.OperatorMemoryStore` with a
persistent Postgres table so scope-narrowed operator notes survive
process restarts and can be queried by the composer on every T2 event
(Wave 3 step C-2). The in-memory implementation in
:mod:`fdai.core.operator_memory.store.InMemoryOperatorMemoryStore`
mirrors the schema; this migration only creates the physical backing.

Columns
-------
- ``id`` - UUID primary key, supplied by the caller (the composer keeps
  the same id across the append + supersede lifecycle).
- ``scope_kind`` - ``'resource-group'`` or ``'resource'`` only.
  Anything broader is a rule retirement, not an override, and MUST flow
  through the catalog pipeline; the CHECK constraint enforces this at
  the boundary even if a future Python enum accidentally widens the
  policy.
- ``scope_ref`` - the exact scope reference the composer resolves
  against. Free-form (fork supplies the ARM-id parser); NOT NULL and
  non-empty after trim.
- ``category`` - one of ``preference``, ``override-note``,
  ``forbidden-action``, ``runbook-hint`` - the composer weighs each
  category slightly differently at assembly time. Free-form text is
  rejected so a malicious body cannot bypass the category weighting.
- ``body`` - the note text. Non-empty after trim (defense in depth
  against a bug that skips the Python-side validator).
- ``source_event`` + ``source_ref`` - provenance pair. Wave 3 step B
  initially seeds only ``hil.reject``; later waves extend the
  taxonomy without a schema change.
- ``author`` / ``approved_by`` - the operator who wrote the entry
  and the second, distinct operator who approved it. The CHECK
  constraint refuses self-approval so a caller bypassing the Python
  policy still cannot land an unreviewed entry.
- ``created_at`` - server-side timestamp; TTL evaluation compares to
  this column.
- ``superseded_by`` - self-referential FK; when a later entry
  replaces this one the pointer is threaded here. Append-only means
  the original row is never updated in body or category.
- ``ttl_seconds`` - positive INTEGER or NULL (indefinite lifetime,
  permitted per the Human Override policy).

Indexes
-------
- Primary key on ``id`` (composer's supersede lookup).
- Composite ``(scope_kind, scope_ref)`` index for the "active for
  scope" query that runs on every T2 event.
- Partial index on ``(superseded_by)`` where ``superseded_by IS NULL``
  is intentionally NOT added: the "active" filter already narrows
  through the scope index; a separate partial buys nothing until the
  table exceeds ~10^5 rows.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260706_0006"
down_revision: str | None = "20260706_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS operator_memory (
            id             UUID PRIMARY KEY,
            scope_kind     TEXT NOT NULL
                CHECK (scope_kind IN ('resource-group', 'resource')),
            scope_ref      TEXT NOT NULL
                CHECK (btrim(scope_ref) <> ''),
            category       TEXT NOT NULL
                CHECK (category IN (
                    'preference',
                    'override-note',
                    'forbidden-action',
                    'runbook-hint'
                )),
            body           TEXT NOT NULL
                CHECK (btrim(body) <> ''),
            source_event   TEXT NOT NULL,
            source_ref     TEXT NOT NULL,
            author         TEXT NOT NULL
                CHECK (btrim(author) <> ''),
            approved_by    TEXT NOT NULL
                CHECK (btrim(approved_by) <> ''),
            created_at     TIMESTAMPTZ NOT NULL,
            superseded_by  UUID NULL REFERENCES operator_memory(id),
            ttl_seconds    INTEGER NULL
                CHECK (ttl_seconds IS NULL OR ttl_seconds > 0),
            CONSTRAINT operator_memory_distinct_approver
                CHECK (
                    lower(btrim(author)) <> lower(btrim(approved_by))
                )
        );
    """)

    op.execute("""
        CREATE INDEX idx_operator_memory_scope
        ON operator_memory (scope_kind, scope_ref);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS operator_memory CASCADE;")
