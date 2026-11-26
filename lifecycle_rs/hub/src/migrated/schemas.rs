#[derive(Clone, Debug, Default, PartialEq)]
pub struct EntityDeclaration {
    pub entity_id: String,
    pub kind: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EnrollmentPayload {
    pub installation_id: String,
    pub installation_key: Vec<u8>,
    pub requested_at: String,
    pub settings: String,
    pub configuration: String,
    pub entities: Vec<EntityDeclaration>,
    pub reported: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SignedEnrollment {
    pub signed_payload: Vec<u8>,
    pub proof: Vec<u8>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ApprovalRequest {
    pub approver: String,
    pub installation_key_id: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RejectionRequest {
    pub approver: String,
    pub reason: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SuppressionCommandRequest {
    pub scope: String,
    pub starts_at: String,
    pub ends_at: String,
    pub reason: String,
    pub confirmation: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LiftSuppressionRequest {
    pub scope: String,
    pub reason: String,
    pub confirmation: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PlanReport {
    pub attempt: i64,
    pub outcome: String,
    pub reason_code: String,
    pub exact_plan_digest: Option<String>,
    pub summary: String,
    pub reported_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecordedReport {
    pub plan_id: String,
    pub received_at: String,
}

impl EnrollmentPayload {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn entities_are_declared_once_and_reported(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
}

impl PlanReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn outcome_rules(&self) -> Result<String, &'static str> {
        if ((self.outcome.clone()) != (String::from("rejected"))) && (self.exact_plan_digest.is_none()) {
            return Err("a self.outcome report must carry exact_plan_digest");
        }
        Ok(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn strict_base64(mut value: String) -> Result<Vec<u8>, &'static str> {
    if !(true) {
        return Err("expected base64 text");
    }
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn maintenance_window_record(mut window: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("start"), String::new()), (String::from("duration_minutes"), String::new()), (String::from("timezone"), String::new()), (String::from("allows_downtime"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn sign_enrollment(mut template: std::collections::BTreeMap<String, String>, mut key: String, mut at: String) -> String {
    enrollment_request(Vec::new(), Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn enrollment_request(mut signed_payload: Vec<u8>, mut proof: Vec<u8>) -> String {
    if signed_payload.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn outcome_record(mut outcome: String) -> std::collections::BTreeMap<String, String> {
    let record: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("outcome"), String::new()), (String::from("checks"), String::new())]);
    record.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn installation_summary_record(mut overview: String, mut now: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("installation_id"), String::new()), (String::from("channel"), String::new()), (String::from("version_range"), String::new()), (String::from("current_release"), String::new()), (String::from("target_release_id"), String::new()), (String::from("outcome"), String::new()), (String::from("health"), String::new()), (String::from("next_window_starts_at"), String::new()), (String::from("next_window_ends_at"), String::new()), (String::from("next_window_open"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn installation_detail_record(mut installation: String, mut enrollment: String, mut open_plan: Option<String>, mut last_evaluation: Option<String>, mut reports: Vec<RecordedReport>, mut now: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("installation_id"), String::new()), (String::from("enrollment"), enrollment.clone()), (String::from("settings"), String::new()), (String::from("configuration_digest"), String::new()), (String::from("reported_at"), String::new()), (String::from("schema_revision"), String::new()), (String::from("current_release"), String::new()), (String::from("health"), String::new()), (String::from("entities"), String::new()), (String::from("suppressions"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn plan_record(mut record: String, mut installation_id: String, mut reports: Vec<RecordedReport>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("plan_id"), String::new()), (String::from("installation_id"), installation_id.clone()), (String::from("sequence"), String::new()), (String::from("plan_type"), String::new()), (String::from("target_release_id"), String::new()), (String::from("source_state_digest"), String::new()), (String::from("configuration_digest"), String::new()), (String::from("hub_key_id"), String::new()), (String::from("entity_ids"), String::new()), (String::from("expires_at"), String::new()), (String::from("status"), String::new()), (String::from("events"), String::new()), (String::from("evaluations"), String::new()), (String::from("reports"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn pending_enrollment_record(mut pending: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("installation_id"), String::new()), (String::from("installation_key_id"), String::new()), (String::from("requested_at"), String::new()), (String::from("requested_by"), String::new()), (String::from("requested_via"), String::new()), (String::from("channel"), String::new()), (String::from("version_range"), String::new()), (String::from("region"), String::new()), (String::from("entities"), String::new()), (String::from("reported_at"), String::new()), (String::from("schema_revision"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn sorted_entities(mut installation: String) -> Vec<String> {
    if installation.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn entity_record(mut entity: String, mut reported: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("entity_id"), String::new()), (String::from("kind"), String::new()), (String::from("managed"), String::new()), (String::from("ownership_gap"), String::new()), (String::from("release_id"), String::new()), (String::from("health"), String::new())])
}

