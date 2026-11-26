-- Migration Revision: operator_browser_evidence_read_20260815
-- Down Revision: operator_conversation_search_read_20260814
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
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
