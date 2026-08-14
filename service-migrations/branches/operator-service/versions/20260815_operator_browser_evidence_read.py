"""Grant the Operator runtime column-scoped browser-evidence metadata access."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_browser_evidence_read_20260815"
down_revision: str | Sequence[str] | None = "operator_conversation_search_read_20260814"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-operator-browser-evidence-read",
    "restores": "operator_conversation_search_read_20260814",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Expose only scalar metadata and derived counts through a guarded view."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE browser_evidence_artifact
        FROM PUBLIC, fdai_operator;
        CREATE VIEW operator_browser_evidence_metadata
        WITH (security_barrier = true) AS
        SELECT artifact_id, policy_id, policy_version,
               canonical_source_url, canonical_final_url,
               captured_at, expires_at,
               JSONB_ARRAY_LENGTH(selectors) AS selector_count,
               screenshot_hash, text_hash, snapshot_hash,
               JSONB_ARRAY_LENGTH(redaction_manifest) AS redaction_count,
               browser_version, chain_of_custody_audit_ref,
               JSONB_ARRAY_LENGTH(prompt_injection_findings)
                   AS prompt_injection_finding_count,
               isolation = JSONB_BUILD_OBJECT(
                   'executor_identity_present', FALSE,
                   'host_filesystem_mounted', FALSE,
                   'environment_scrubbed', TRUE,
                   'restricted_egress', TRUE,
                   'ephemeral_profile', TRUE
               ) AS isolation_verified,
               untrusted, legal_hold, legal_hold_ref, legal_hold_at
          FROM browser_evidence_artifact;
        REVOKE ALL PRIVILEGES ON TABLE operator_browser_evidence_metadata
        FROM PUBLIC;
        GRANT SELECT ON TABLE operator_browser_evidence_metadata TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove browser-evidence metadata access from the Operator role."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE operator_browser_evidence_metadata
        FROM fdai_operator;
        DROP VIEW operator_browser_evidence_metadata;
        REVOKE ALL PRIVILEGES ON TABLE browser_evidence_artifact
        FROM fdai_operator
        """
    )
