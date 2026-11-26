pub const COST_DISCLOSURE_RETENTION_DAYS: i64 = 400;
pub const COST_DISCLOSURE_PURGE_GRACE_DAYS: i64 = 30;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostActivationSnapshot {
    pub vertical_id: String,
    pub package_id: String,
    pub available: bool,
    pub enabled: bool,
    pub availability_reasons: Vec<String>,
    pub package_version: String,
    pub image_digest: String,
    pub asset_manifest_digest: String,
    pub semantic_profile_digest: String,
    pub ontology_release_digest: String,
    pub revision: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostAccessDecision {
    pub grant: Option<String>,
    pub ceiling: Option<String>,
    pub reason: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostDisclosureAuditRecord {
    pub decision_id: String,
    pub principal_digest: String,
    pub scope_digest: String,
    pub surface: String,
    pub grant_revision: i64,
    pub ceiling_revision: i64,
    pub activation_revision: i64,
    pub disclosure_digest: String,
    pub record_count: i64,
    pub suppressed_count: i64,
    pub occurred_at: String,
    pub retention_until: String,
    pub legal_hold: bool,
    pub legal_hold_ref: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostProjectionEvidenceSnapshot {
    pub window_start_at: Option<String>,
    pub window_end_at: Option<String>,
    pub latest_source_at: Option<String>,
    pub complete_count: i64,
    pub partial_count: i64,
    pub sources: Vec<String>,
    pub latest_analytics_run: Option<String>,
    pub resource_candidate_count: i64,
    pub incomplete_candidate_count: i64,
    pub decision_case_count: i64,
    pub incomplete_decision_case_count: i64,
    pub settlement_count: i64,
    pub incomplete_settlement_count: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostAnalyticsSnapshot {
    pub snapshot_id: String,
    pub scope_id: String,
    pub projection: String,
}

pub trait CostAccessReader {
    fn read_access(&self, principal_id: String, purpose: String, scope: String, now: String) -> String;
}

pub trait CostActivationReader {
    fn read_activation(&self, package_id: String) -> String;
}

pub trait CostActivationWriter {
    fn set_enabled(&self, package_id: String, actor_id: String, enabled: bool, expected_revision: i64, request_id: String) -> String;
}

pub trait CostProjectionReader {
    fn read_records(&self, surface: String, scope: String, limit: i64) -> String;
}

pub trait CostAnalyticsReader {
    fn read_analytics(&self, scope: String) -> String;
}

pub trait CostDisclosureAuditWriter {
    fn append_disclosure_audit(&self, record: CostDisclosureAuditRecord) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn decode_cost_pseudonym_key(mut value: Option<String>) -> Result<Option<Vec<u8>>, &'static str> {
    if (value.is_none()) || ((((value.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
        return Ok(None);
    }
    let normalized: String = ((value.clone()).unwrap_or_default()).trim().to_string();
    Ok(None)
}

pub const PUBLIC_EXPORTS: &[&str] = &["COST_DISCLOSURE_PURGE_GRACE_DAYS", "COST_DISCLOSURE_RETENTION_DAYS", "CostAccessDecision", "CostAccessReader", "CostAnalyticsSnapshot", "CostAnalyticsReader", "CostActivationReader", "CostActivationSnapshot", "CostActivationWriter", "CostDisclosureAuditRecord", "CostDisclosureAuditWriter", "CostProjectionReader", "CostProjectionEvidenceSnapshot", "decode_cost_pseudonym_key"];
