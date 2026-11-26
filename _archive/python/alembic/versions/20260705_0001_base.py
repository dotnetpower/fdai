"""base ontology + audit_log

Revision ID: 20260705_0001
Revises:
Create Date: 2026-07-05 00:00:00

Establishes the persistent-state schema referenced by
``docs/roadmap/architecture/project-structure.md`` and the audit hash-chain contract in
``docs/roadmap/architecture/security-and-identity.md``.

Raw SQL only - no ORM metadata is imported so the schema evolves
independently of any Python model (the fake ``InMemoryStateStore`` mirrors
these tables in-memory for tests).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260705_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ontology_object_type (
            name        TEXT PRIMARY KEY,
            version     TEXT NOT NULL,
            key_field   TEXT NOT NULL,
            properties  JSONB NOT NULL,
            description TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS ontology_link_type (
            name        TEXT PRIMARY KEY,
            version     TEXT NOT NULL,
            from_type   TEXT NOT NULL REFERENCES ontology_object_type(name),
            to_type     TEXT NOT NULL REFERENCES ontology_object_type(name),
            cardinality TEXT NOT NULL
                CHECK (cardinality IN ('one_to_one','one_to_many','many_to_one','many_to_many')),
            description TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS ontology_resource (
            id          TEXT PRIMARY KEY,
            object_type TEXT NOT NULL REFERENCES ontology_object_type(name),
            properties  JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX idx_ontology_resource_object_type ON ontology_resource(object_type);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS ontology_finding (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_id      TEXT NOT NULL,
            resource_ref TEXT NOT NULL REFERENCES ontology_resource(id),
            severity     TEXT NOT NULL
                CHECK (severity IN ('critical','high','medium','low')),
            state        TEXT NOT NULL
                CHECK (state IN ('open','resolved','suppressed')),
            details      JSONB NOT NULL DEFAULT '{}'::jsonb,
            detected_at  TIMESTAMPTZ NOT NULL,
            resolved_at  TIMESTAMPTZ
        );
    """)
    op.execute("CREATE INDEX idx_ontology_finding_rule_id ON ontology_finding(rule_id);")
    op.execute("CREATE INDEX idx_ontology_finding_resource_ref ON ontology_finding(resource_ref);")
    op.execute("CREATE INDEX idx_ontology_finding_state ON ontology_finding(state);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS ontology_link (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            link_type  TEXT NOT NULL REFERENCES ontology_link_type(name),
            from_id    TEXT NOT NULL,
            to_id      TEXT NOT NULL,
            properties JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX idx_ontology_link_from ON ontology_link(from_id);")
    op.execute("CREATE INDEX idx_ontology_link_to   ON ontology_link(to_id);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            seq            BIGSERIAL PRIMARY KEY,
            event_id       UUID NOT NULL,
            correlation_id TEXT,
            actor          TEXT NOT NULL,
            action_kind    TEXT NOT NULL,
            mode           TEXT NOT NULL CHECK (mode IN ('shadow','enforce')),
            entry          JSONB NOT NULL,
            previous_hash  TEXT NOT NULL,
            entry_hash     TEXT NOT NULL UNIQUE,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX idx_audit_log_event_id ON audit_log(event_id);")
    op.execute(
        "CREATE INDEX idx_audit_log_correlation_id ON audit_log(correlation_id) "
        "WHERE correlation_id IS NOT NULL;"
    )


def downgrade() -> None:
    # Reverse creation order so FK references drop cleanly.
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE;")
    op.execute("DROP TABLE IF EXISTS ontology_link CASCADE;")
    op.execute("DROP TABLE IF EXISTS ontology_finding CASCADE;")
    op.execute("DROP TABLE IF EXISTS ontology_resource CASCADE;")
    op.execute("DROP TABLE IF EXISTS ontology_link_type CASCADE;")
    op.execute("DROP TABLE IF EXISTS ontology_object_type CASCADE;")
