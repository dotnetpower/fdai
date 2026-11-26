//! PostgreSQL Bitemporal Ontology, Azure Telemetry Series, and Causal Evidence SQL Builders.
//!
//! Strictly enforces SQL literal escaping (`pg_quote_literal`), finite numeric invariants,
//! `as_of` cutoff bounds (no future-sample leakage), and identifier hygiene before querying
//! PostgreSQL through `PgWireClient`.

use crate::{pg_quote_literal, PgConnectionConfig, PgQueryResult, PgWireClient};
use fdai_ports::TemporalCausalStorePort;

#[derive(Clone, Debug, PartialEq)]
pub struct CausalEdgeEvidenceRecord {
    pub subscription_id: String,
    pub cause_concept: String,
    pub relation_type: String,
    pub effect_concept: String,
    pub evidence_grade: String,
    pub optimal_lag_seconds: i64,
    pub granger_r2_gain: f64,
    pub confounder_controlled: bool,
    pub counterfactual_verified: bool,
    pub evidence_cutoff_iso: String,
    pub graph_digest: String,
}

fn is_valid_iso_ts(ts: &str) -> bool {
    let tr = ts.trim();
    tr.len() >= 19
        && tr.len() <= 40
        && tr.as_bytes()[4] == b'-'
        && tr.as_bytes()[7] == b'-'
        && !tr.chars().any(|c| c.is_control() || matches!(c, '\'' | ';' | '\\'))
}

fn is_valid_concept_slug(s: &str) -> bool {
    let tr = s.trim();
    !tr.is_empty()
        && tr.len() <= 128
        && tr
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-' | ':' | '.'))
}

/// Build an injection-safe SQL query fetching the bitemporal ontology topology valid at
/// `(as_of_iso, effective_iso)` without mixing future edges or later graph generations.
pub fn build_bitemporal_topology_as_of_sql(
    subscription_id: &str,
    as_of_iso: &str,
    effective_iso: &str,
) -> Result<String, &'static str> {
    if subscription_id.trim().is_empty() || subscription_id.len() > 128 {
        return Err("subscription_id must be non-empty and <= 128 chars");
    }
    if !is_valid_iso_ts(as_of_iso) || !is_valid_iso_ts(effective_iso) {
        return Err("as_of_iso and effective_iso must be valid ISO-8601 timestamps");
    }
    if effective_iso.trim() > as_of_iso.trim() {
        return Err("effective_iso must not exceed as_of_iso");
    }
    let sub_q = pg_quote_literal(subscription_id.trim());
    let as_of_q = pg_quote_literal(as_of_iso.trim());
    let eff_q = pg_quote_literal(effective_iso.trim());
    Ok(format!(
        "SELECT source_ref, relation_type, target_ref, weight, unless_inhibitors, graph_generation \
         FROM ontology_topology_bitemporal \
         WHERE subscription_id = {sub_q} \
           AND recorded_at <= {as_of_q}::timestamptz \
           AND valid_from <= {eff_q}::timestamptz \
           AND (valid_to IS NULL OR valid_to > {eff_q}::timestamptz) \
         ORDER BY graph_generation ASC, recorded_at ASC"
    ))
}

/// Build an injection-safe SQL query fetching Azure resource change & metric telemetry
/// strictly bounded by `valid_at <= cutoff_iso` and `ingested_at <= cutoff_iso`.
pub fn build_azure_telemetry_window_sql(
    resource_id: &str,
    concept: &str,
    from_iso: &str,
    cutoff_iso: &str,
    limit: usize,
) -> Result<String, &'static str> {
    if resource_id.trim().is_empty() || resource_id.len() > 512 {
        return Err("resource_id must be non-empty and <= 512 chars");
    }
    if !is_valid_concept_slug(concept) {
        return Err("concept must be a clean ASCII slug");
    }
    if !is_valid_iso_ts(from_iso) || !is_valid_iso_ts(cutoff_iso) {
        return Err("from_iso and cutoff_iso must be valid ISO-8601 timestamps");
    }
    if from_iso.trim() > cutoff_iso.trim() {
        return Err("from_iso must not exceed cutoff_iso");
    }
    let res_q = pg_quote_literal(resource_id.trim());
    let con_q = pg_quote_literal(concept.trim());
    let from_q = pg_quote_literal(from_iso.trim());
    let cut_q = pg_quote_literal(cutoff_iso.trim());
    let lim = limit.clamp(1, 4096);
    Ok(format!(
        "SELECT (EXTRACT(EPOCH FROM valid_at) * 1000)::bigint AS valid_at_ms, value, status_tag \
         FROM azure_telemetry_series \
         WHERE resource_id = {res_q} \
           AND metric_or_change_concept = {con_q} \
           AND valid_at >= {from_q}::timestamptz \
           AND valid_at <= {cut_q}::timestamptz \
           AND ingested_at <= {cut_q}::timestamptz \
         ORDER BY valid_at ASC \
         LIMIT {lim}"
    ))
}

/// Build an injection-safe SQL upsert persisting an empirically verified causal edge
/// into `causal_edge_evidence` while rejecting polluted labels or non-finite scores.
pub fn build_upsert_causal_edge_evidence_sql(
    rec: &CausalEdgeEvidenceRecord,
) -> Result<String, &'static str> {
    if rec.subscription_id.trim().is_empty() || rec.subscription_id.len() > 128 {
        return Err("invalid subscription_id");
    }
    if !is_valid_concept_slug(&rec.cause_concept)
        || !is_valid_concept_slug(&rec.effect_concept)
        || !is_valid_concept_slug(&rec.relation_type)
        || !is_valid_concept_slug(&rec.evidence_grade)
    {
        return Err("polluted causal concept, relation, or grade rejected");
    }
    if !rec.granger_r2_gain.is_finite() || !(0.0..=1.0).contains(&rec.granger_r2_gain) {
        return Err("granger_r2_gain must be finite within 0.0..=1.0");
    }
    if rec.optimal_lag_seconds < 0 || !is_valid_iso_ts(&rec.evidence_cutoff_iso) {
        return Err("invalid lag or evidence_cutoff_iso");
    }
    if rec.graph_digest.trim().is_empty() || rec.graph_digest.len() > 128 {
        return Err("graph_digest must be non-empty and <= 128 chars");
    }
    let sub_q = pg_quote_literal(rec.subscription_id.trim());
    let cause_q = pg_quote_literal(rec.cause_concept.trim());
    let rel_q = pg_quote_literal(rec.relation_type.trim());
    let eff_q = pg_quote_literal(rec.effect_concept.trim());
    let grade_q = pg_quote_literal(rec.evidence_grade.trim());
    let cut_q = pg_quote_literal(rec.evidence_cutoff_iso.trim());
    let dig_q = pg_quote_literal(rec.graph_digest.trim());
    Ok(format!(
        "INSERT INTO causal_edge_evidence (\
             subscription_id, cause_concept, relation_type, effect_concept, evidence_grade, \
             optimal_lag_seconds, granger_r2_gain, confounder_controlled, counterfactual_verified, \
             evidence_cutoff, graph_digest, updated_at\
         ) VALUES (\
             {sub_q}, {cause_q}, {rel_q}, {eff_q}, {grade_q}, \
             {}, {:.6}, {}, {}, {cut_q}::timestamptz, {dig_q}, NOW()\
         ) \
         ON CONFLICT (subscription_id, cause_concept, relation_type, effect_concept) DO UPDATE SET \
             evidence_grade = EXCLUDED.evidence_grade, \
             optimal_lag_seconds = EXCLUDED.optimal_lag_seconds, \
             granger_r2_gain = EXCLUDED.granger_r2_gain, \
             confounder_controlled = EXCLUDED.confounder_controlled, \
             counterfactual_verified = EXCLUDED.counterfactual_verified, \
             evidence_cutoff = EXCLUDED.evidence_cutoff, \
             graph_digest = EXCLUDED.graph_digest, \
             updated_at = NOW()",
        rec.optimal_lag_seconds,
        rec.granger_r2_gain,
        rec.confounder_controlled,
        rec.counterfactual_verified,
    ))
}

/// PostgreSQL adapter implementing `TemporalCausalStorePort` over `PgWireClient`.
#[derive(Clone, Debug)]
pub struct PgTemporalCausalAdapter {
    pub config: PgConnectionConfig,
}

impl PgTemporalCausalAdapter {
    #[must_use]
    pub const fn new(config: PgConnectionConfig) -> Self {
        Self { config }
    }

    pub async fn fetch_topology_as_of(
        &self,
        subscription_id: &str,
        as_of_iso: &str,
        effective_iso: &str,
    ) -> Result<PgQueryResult, String> {
        let sql = build_bitemporal_topology_as_of_sql(subscription_id, as_of_iso, effective_iso)
            .map_err(String::from)?;
        PgWireClient::query_once(&self.config, &sql).await
    }

    pub async fn fetch_telemetry_window(
        &self,
        resource_id: &str,
        concept: &str,
        from_iso: &str,
        cutoff_iso: &str,
        limit: usize,
    ) -> Result<PgQueryResult, String> {
        let sql =
            build_azure_telemetry_window_sql(resource_id, concept, from_iso, cutoff_iso, limit)
                .map_err(String::from)?;
        PgWireClient::query_once(&self.config, &sql).await
    }

    pub async fn upsert_causal_edge_evidence(
        &self,
        rec: &CausalEdgeEvidenceRecord,
    ) -> Result<PgQueryResult, String> {
        let sql = build_upsert_causal_edge_evidence_sql(rec).map_err(String::from)?;
        PgWireClient::query_once(&self.config, &sql).await
    }
}

impl TemporalCausalStorePort for PgTemporalCausalAdapter {
    fn build_topology_as_of_query(
        &self,
        subscription_id: &str,
        as_of_iso: &str,
        effective_iso: &str,
    ) -> Result<String, &'static str> {
        build_bitemporal_topology_as_of_sql(subscription_id, as_of_iso, effective_iso)
    }

    fn build_telemetry_window_query(
        &self,
        resource_id: &str,
        concept: &str,
        from_iso: &str,
        cutoff_iso: &str,
        limit: usize,
    ) -> Result<String, &'static str> {
        build_azure_telemetry_window_sql(resource_id, concept, from_iso, cutoff_iso, limit)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn postgres_temporal_causal_sql_enforces_as_of_and_rejects_injection() -> Result<(), &'static str> {
        let topo = build_bitemporal_topology_as_of_sql(
            "sub-prod-01",
            "2026-10-01T10:15:00Z",
            "2026-10-01T10:10:00Z",
        )?;
        assert!(topo.contains("recorded_at <= '2026-10-01T10:15:00Z'::timestamptz"));
        assert!(topo.contains("valid_from <= '2026-10-01T10:10:00Z'::timestamptz"));

        // Effective > as_of rejected
        assert!(build_bitemporal_topology_as_of_sql(
            "sub-prod-01",
            "2026-10-01T10:00:00Z",
            "2026-10-01T10:30:00Z",
        )
        .is_err());

        // Telemetry query strictly bounds both valid_at and ingested_at <= cutoff
        let tel = build_azure_telemetry_window_sql(
            "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-1",
            "http_5xx_or_zero",
            "2026-10-01T09:00:00Z",
            "2026-10-01T10:00:00Z",
            500,
        )?;
        assert!(tel.contains("ingested_at <= '2026-10-01T10:00:00Z'::timestamptz"));
        assert!(tel.contains("LIMIT 500"));

        // SQL injection in concept rejected
        assert!(build_azure_telemetry_window_sql(
            "res-1",
            "cpu; DROP TABLE azure_telemetry_series;",
            "2026-10-01T09:00:00Z",
            "2026-10-01T10:00:00Z",
            10,
        )
        .is_err());

        let rec = CausalEdgeEvidenceRecord {
            subscription_id: String::from("sub-prod-01"),
            cause_concept: String::from("nsg_rule_change"),
            relation_type: String::from("causes"),
            effect_concept: String::from("connection_failures"),
            evidence_grade: String::from("temporal_granger_supported"),
            optimal_lag_seconds: 60,
            granger_r2_gain: 0.4821,
            confounder_controlled: true,
            counterfactual_verified: false,
            evidence_cutoff_iso: String::from("2026-10-01T10:15:00Z"),
            graph_digest: String::from("sha256:0123456789abcdef"),
        };
        let up = build_upsert_causal_edge_evidence_sql(&rec)?;
        assert!(up.contains("INSERT INTO causal_edge_evidence"));
        assert!(up.contains("ON CONFLICT (subscription_id, cause_concept, relation_type, effect_concept)"));
        Ok(())
    }
}
