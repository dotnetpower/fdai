-- Migration Revision: operator_chaos_report_read_20260921
-- Down Revision: operator_cost_governance_live_read_20260917
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE report_signal FROM fdai_operator;
        CREATE VIEW operator_chaos_report_signal
        WITH (security_barrier = true) AS
        SELECT signal_id, severity, resource_ref, occurred_at,
               metadata ->> 'scenario_id' AS scenario_id,
               metadata ->> 'outcome' AS outcome,
               metadata ->> 'mode' AS mode,
               metadata ->> 'expected_signal' AS expected_signal,
               (metadata ->> 'detected')::boolean AS detected,
               (metadata ->> 'reverted')::boolean AS reverted,
               (metadata ->> 'injected')::boolean AS injected,
               (metadata ->> 'stopped')::boolean AS stopped,
               metadata ->> 'approval_ref' AS approval_ref
          FROM report_signal
         WHERE kind = 'chaos'
           AND category = 'workload'
           AND severity IN ('critical', 'high', 'medium', 'low')
           AND metadata ->> 'outcome' IN (
               'validated', 'not_detected', 'aborted',
               'blast_radius_exceeded', 'rollback_failed', 'shadowed'
           )
           AND metadata ->> 'mode' IN ('shadow', 'enforce')
           AND metadata ->> 'detected' IN ('true', 'false')
           AND metadata ->> 'reverted' IN ('true', 'false')
           AND metadata ->> 'injected' IN ('true', 'false')
           AND metadata ->> 'stopped' IN ('true', 'false')
           AND NULLIF(metadata ->> 'scenario_id', '') IS NOT NULL
           AND NULLIF(metadata ->> 'expected_signal', '') IS NOT NULL
           AND NULLIF(metadata ->> 'approval_ref', '') IS NOT NULL;
        REVOKE ALL PRIVILEGES ON TABLE operator_chaos_report_signal FROM PUBLIC;
        GRANT SELECT ON TABLE operator_chaos_report_signal TO fdai_operator;
