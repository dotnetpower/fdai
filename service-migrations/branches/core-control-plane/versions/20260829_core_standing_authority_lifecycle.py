"""Persist append-only A3-E lifecycle state and dispatch fences."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_standing_authority_lifecycle_20260829"
down_revision: str | Sequence[str] | None = "core_cost_governance_validation_20260829"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "standing_authorization_family",
    "standing_authorization_revision",
    "standing_authorization_transition",
    "standing_authorization_snapshot",
    "standing_authorization_audit",
)
rollback = {
    "strategy": "drop-standing-authority-lifecycle-after-shadow-readers-stop",
    "restores": "core_cost_governance_validation_20260829",
    "requires": "standing-authority-shadow-readers-stopped",
}


def upgrade() -> None:
    """Create immutable revisions, chained transitions, projection, and audit."""

    op.execute(
        """
        CREATE TABLE standing_authorization_family (
            family_id TEXT PRIMARY KEY
                CHECK (char_length(family_id) BETWEEN 1 AND 512)
        );

        CREATE TABLE standing_authorization_revision (
            revision_id TEXT PRIMARY KEY
                CHECK (revision_id ~ '^sha256:[0-9a-f]{64}$'),
            family_id TEXT NOT NULL
                REFERENCES standing_authorization_family(family_id),
            predecessor_revision_id TEXT NULL
                REFERENCES standing_authorization_revision(revision_id),
            issued_at TIMESTAMPTZ NOT NULL,
            terms JSONB NOT NULL CHECK (jsonb_typeof(terms) = 'object'),
            document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object'),
            approval_claim_digest TEXT NOT NULL
                CHECK (approval_claim_digest ~ '^sha256:[0-9a-f]{64}$'),
            approvals_digest TEXT NOT NULL
                UNIQUE CHECK (approvals_digest ~ '^sha256:[0-9a-f]{64}$'),
            evidence_claim_digest TEXT NOT NULL
                CHECK (evidence_claim_digest ~ '^sha256:[0-9a-f]{64}$'),
            evidence_verification_bundle_digest TEXT NOT NULL
                UNIQUE CHECK (
                    evidence_verification_bundle_digest ~ '^sha256:[0-9a-f]{64}$'
                ),
            UNIQUE (family_id, revision_id),
            CHECK (
                (predecessor_revision_id IS NULL)
                OR predecessor_revision_id <> revision_id
            )
        );

        CREATE TABLE standing_authorization_transition (
            family_id TEXT NOT NULL
                REFERENCES standing_authorization_family(family_id),
            sequence BIGINT NOT NULL CHECK (sequence >= 1),
            kind TEXT NOT NULL CHECK (kind IN ('admit', 'renew', 'revoke')),
            command_id TEXT NOT NULL
                CHECK (char_length(command_id) BETWEEN 1 AND 512),
            command_digest TEXT NOT NULL
                CHECK (command_digest ~ '^sha256:[0-9a-f]{64}$'),
            actor_ref TEXT NOT NULL
                CHECK (char_length(actor_ref) BETWEEN 1 AND 512),
            actor_roles JSONB NOT NULL CHECK (
                jsonb_typeof(actor_roles) = 'array'
                AND jsonb_array_length(actor_roles) BETWEEN 1 AND 16
            ),
            authentication_evidence_digest TEXT NOT NULL
                CHECK (authentication_evidence_digest ~ '^sha256:[0-9a-f]{64}$'),
            authenticated_at TIMESTAMPTZ NOT NULL,
            correlation_id TEXT NOT NULL
                CHECK (char_length(correlation_id) BETWEEN 1 AND 512),
            revision_id TEXT NOT NULL
                REFERENCES standing_authorization_revision(revision_id),
            predecessor_revision_id TEXT NULL,
            fencing_generation BIGINT NOT NULL CHECK (fencing_generation >= 1),
            occurred_at TIMESTAMPTZ NOT NULL,
            previous_transition_digest TEXT NULL,
            transition_digest TEXT NOT NULL UNIQUE
                CHECK (transition_digest ~ '^sha256:[0-9a-f]{64}$'),
            PRIMARY KEY (family_id, sequence),
            UNIQUE (command_id),
            UNIQUE (family_id, fencing_generation),
            FOREIGN KEY (family_id, revision_id)
                REFERENCES standing_authorization_revision(family_id, revision_id),
            FOREIGN KEY (predecessor_revision_id)
                REFERENCES standing_authorization_revision(revision_id),
            FOREIGN KEY (previous_transition_digest)
                REFERENCES standing_authorization_transition(transition_digest),
            CHECK (authenticated_at <= occurred_at),
            CHECK (
                previous_transition_digest IS NULL
                OR previous_transition_digest ~ '^sha256:[0-9a-f]{64}$'
            )
        );

        CREATE TABLE standing_authorization_snapshot (
            family_id TEXT PRIMARY KEY
                REFERENCES standing_authorization_family(family_id),
            current_revision_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
            fencing_generation BIGINT NOT NULL CHECK (fencing_generation >= 1),
            last_sequence BIGINT NOT NULL CHECK (last_sequence >= 1),
            head_transition_digest TEXT NOT NULL
                REFERENCES standing_authorization_transition(transition_digest),
            snapshot_digest TEXT NOT NULL
                CHECK (snapshot_digest ~ '^sha256:[0-9a-f]{64}$'),
            FOREIGN KEY (family_id, current_revision_id)
                REFERENCES standing_authorization_revision(family_id, revision_id),
            FOREIGN KEY (family_id, last_sequence)
                REFERENCES standing_authorization_transition(family_id, sequence)
        );

        CREATE TABLE standing_authorization_audit (
            transition_digest TEXT PRIMARY KEY
                REFERENCES standing_authorization_transition(transition_digest),
            family_id TEXT NOT NULL,
            sequence BIGINT NOT NULL,
            audit_digest TEXT NOT NULL UNIQUE
                CHECK (audit_digest ~ '^sha256:[0-9a-f]{64}$'),
            entry JSONB NOT NULL CHECK (jsonb_typeof(entry) = 'object'),
            FOREIGN KEY (family_id, sequence)
                REFERENCES standing_authorization_transition(family_id, sequence)
        );

        CREATE INDEX standing_authorization_transition_revision_idx
            ON standing_authorization_transition (revision_id, sequence);
        CREATE INDEX standing_authorization_revision_family_idx
            ON standing_authorization_revision (family_id, issued_at, revision_id);

        REVOKE ALL PRIVILEGES ON TABLE
            standing_authorization_family,
            standing_authorization_revision,
            standing_authorization_transition,
            standing_authorization_snapshot,
            standing_authorization_audit
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT ON TABLE
            standing_authorization_family,
            standing_authorization_revision,
            standing_authorization_transition,
            standing_authorization_audit
        TO fdai_core;
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON TABLE standing_authorization_snapshot TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop shadow lifecycle tables after all readers stop."""

    op.execute(
        """
        DROP TABLE standing_authorization_audit;
        DROP TABLE standing_authorization_snapshot;
        DROP TABLE standing_authorization_transition;
        DROP TABLE standing_authorization_revision;
        DROP TABLE standing_authorization_family;
        """
    )
