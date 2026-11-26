"""Add payload-free Browser evidence workspace projections."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_browser_evidence_workspace_20260915"
down_revision: str | Sequence[str] | None = "operator_handover_admission_20260914"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "drop-browser-evidence-workspace-views",
    "restores": "operator_handover_admission_20260914",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    """Expose admitted metadata and snapshot-wide withholding without payload rows."""

    op.execute(
        """
        CREATE VIEW operator_browser_evidence_admission_internal
        WITH (security_barrier = true) AS
        WITH normalized AS (
            SELECT artifact_id, policy_id, policy_version,
                   canonical_source_url, canonical_final_url,
                   TRIM(BOTH '[]' FROM SPLIT_PART(
                       SPLIT_PART(canonical_source_url, '://', 2), '/', 1
                   )) AS source_host,
                   TRIM(BOTH '[]' FROM SPLIT_PART(
                       SPLIT_PART(canonical_final_url, '://', 2), '/', 1
                   )) AS final_host,
                   captured_at, expires_at, created_at,
                   selectors, screenshot_hash, text_hash, snapshot_hash,
                   redaction_manifest, browser_version,
                   chain_of_custody_audit_ref,
                   CASE
                       WHEN chain_of_custody_audit_ref
                            ~ ('^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-'
                               || '[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
                           THEN chain_of_custody_audit_ref::UUID
                       ELSE NULL
                   END AS custody_audit_uuid,
                   prompt_injection_findings, untrusted, isolation,
                   legal_hold, legal_hold_ref, legal_hold_at
              FROM public.browser_evidence_artifact
        )
        SELECT artifact_id, policy_id, policy_version,
               canonical_source_url, canonical_final_url,
               source_host, final_host,
               captured_at, expires_at, created_at,
               JSONB_ARRAY_LENGTH(selectors) AS selector_count,
               screenshot_hash IS NOT NULL AS has_screenshot_digest,
               text_hash IS NOT NULL AS has_text_digest,
               snapshot_hash IS NOT NULL AS has_snapshot_digest,
               JSONB_ARRAY_LENGTH(redaction_manifest) AS redaction_count,
               browser_version, chain_of_custody_audit_ref,
               custody_audit_uuid,
               JSONB_ARRAY_LENGTH(prompt_injection_findings)
                   AS prompt_injection_finding_count,
               untrusted IS TRUE AS trust_valid,
               isolation = JSONB_BUILD_OBJECT(
                   'executor_identity_present', FALSE,
                   'host_filesystem_mounted', FALSE,
                   'environment_scrubbed', TRUE,
                   'restricted_egress', TRUE,
                   'ephemeral_profile', TRUE
               ) AS isolation_verified,
               (
                   artifact_id ~ '^sha256:[0-9a-f]{64}$'
                   AND length(policy_id) BETWEEN 1 AND 256
                   AND policy_id = BTRIM(policy_id)
                   AND policy_id !~ '[[:cntrl:]]'
                   AND OCTET_LENGTH(policy_id) = length(policy_id)
                   AND policy_version > 0
                   AND length(canonical_source_url) BETWEEN 9 AND 2048
                   AND canonical_source_url ~ '^https://[^/?#]+(?:/|$)'
                   AND canonical_source_url = BTRIM(canonical_source_url)
                   AND canonical_source_url !~ '[[:cntrl:]]'
                   AND canonical_source_url !~ '^https://[^/]*@'
                   AND canonical_source_url !~ '#'
                   AND length(source_host) BETWEEN 1 AND 253
                   AND source_host = LOWER(source_host)
                   AND source_host !~ '[[:space:]]'
                   AND OCTET_LENGTH(source_host) = length(source_host)
                   AND source_host
                       ~ '^[^.]{1,63}([.][^.]{1,63})*[.]?$'
                   AND length(canonical_final_url) BETWEEN 9 AND 2048
                   AND canonical_final_url ~ '^https://[^/?#]+(?:/|$)'
                   AND canonical_final_url = BTRIM(canonical_final_url)
                   AND canonical_final_url !~ '[[:cntrl:]]'
                   AND canonical_final_url !~ '^https://[^/]*@'
                   AND canonical_final_url !~ '#'
                   AND length(final_host) BETWEEN 1 AND 253
                   AND final_host = LOWER(final_host)
                   AND final_host !~ '[[:space:]]'
                   AND OCTET_LENGTH(final_host) = length(final_host)
                   AND final_host
                       ~ '^[^.]{1,63}([.][^.]{1,63})*[.]?$'
                   AND captured_at < expires_at
                   AND created_at >= captured_at
                   AND created_at <= CURRENT_TIMESTAMP
                   AND JSONB_ARRAY_LENGTH(selectors) BETWEEN 0 AND 32
                   AND (
                       screenshot_hash IS NULL
                       OR screenshot_hash ~ '^[0-9a-f]{64}$'
                   )
                   AND (
                       text_hash IS NULL
                       OR text_hash ~ '^[0-9a-f]{64}$'
                   )
                   AND (
                       snapshot_hash IS NULL
                       OR snapshot_hash ~ '^[0-9a-f]{64}$'
                   )
                   AND JSONB_ARRAY_LENGTH(redaction_manifest) BETWEEN 0 AND 4096
                   AND length(browser_version) BETWEEN 1 AND 256
                   AND browser_version = BTRIM(browser_version)
                   AND browser_version !~ '[[:cntrl:]]'
                   AND OCTET_LENGTH(browser_version) = length(browser_version)
                   AND length(chain_of_custody_audit_ref) BETWEEN 1 AND 512
                   AND chain_of_custody_audit_ref
                       = BTRIM(chain_of_custody_audit_ref)
                   AND chain_of_custody_audit_ref !~ '[[:cntrl:]]'
                   AND OCTET_LENGTH(chain_of_custody_audit_ref)
                       = length(chain_of_custody_audit_ref)
                   AND JSONB_ARRAY_LENGTH(prompt_injection_findings)
                       BETWEEN 0 AND 256
                   AND (
                       (legal_hold IS TRUE
                        AND legal_hold_ref IS NOT NULL
                        AND length(legal_hold_ref) BETWEEN 1 AND 512
                        AND legal_hold_ref = BTRIM(legal_hold_ref)
                        AND legal_hold_ref !~ '[[:cntrl:]]'
                        AND OCTET_LENGTH(legal_hold_ref)
                            = length(legal_hold_ref)
                        AND legal_hold_at IS NOT NULL
                        AND legal_hold_at >= captured_at)
                       OR
                       (legal_hold IS FALSE
                        AND legal_hold_ref IS NULL
                        AND legal_hold_at IS NULL)
                   )
               ) AS metadata_valid,
               legal_hold, legal_hold_ref, legal_hold_at
          FROM normalized;

        REVOKE ALL PRIVILEGES
          ON TABLE operator_browser_evidence_admission_internal
        FROM PUBLIC, fdai_operator;

        CREATE VIEW operator_browser_evidence_workspace
        WITH (security_barrier = true) AS
        SELECT artifact_id, policy_id, policy_version,
               source_host, final_host,
               captured_at, expires_at, created_at,
               selector_count,
               has_screenshot_digest, has_text_digest, has_snapshot_digest,
               redaction_count, browser_version, chain_of_custody_audit_ref,
               custody_audit_uuid,
               prompt_injection_finding_count,
               legal_hold, legal_hold_ref, legal_hold_at
          FROM operator_browser_evidence_admission_internal
         WHERE metadata_valid AND trust_valid AND isolation_verified;

        CREATE VIEW operator_browser_evidence_workspace_summary
        WITH (security_barrier = true) AS
        SELECT COUNT(*)::BIGINT AS snapshot_total_count,
               COUNT(*) FILTER (
                   WHERE metadata_valid AND trust_valid AND isolation_verified
               )::BIGINT AS snapshot_admitted_count,
               COUNT(*) FILTER (
                   WHERE NOT metadata_valid
               )::BIGINT AS withheld_invalid_metadata_count,
               COUNT(*) FILTER (
                   WHERE metadata_valid AND NOT trust_valid
               )::BIGINT AS withheld_trust_invalid_count,
               COUNT(*) FILTER (
                   WHERE metadata_valid AND trust_valid AND NOT isolation_verified
               )::BIGINT AS withheld_isolation_unverified_count,
               MAX(created_at) FILTER (
                   WHERE created_at <= CURRENT_TIMESTAMP
               ) AS source_observed_at
          FROM operator_browser_evidence_admission_internal;

        REVOKE ALL PRIVILEGES
          ON TABLE operator_browser_evidence_workspace,
                   operator_browser_evidence_workspace_summary
        FROM PUBLIC;
        GRANT SELECT
          ON TABLE operator_browser_evidence_workspace,
                   operator_browser_evidence_workspace_summary
          TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove only the additive Browser evidence workspace projections."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES
          ON TABLE operator_browser_evidence_workspace,
                   operator_browser_evidence_workspace_summary
        FROM fdai_operator;
        DROP VIEW operator_browser_evidence_workspace_summary;
        DROP VIEW operator_browser_evidence_workspace;
        DROP VIEW operator_browser_evidence_admission_internal;
        """
    )
