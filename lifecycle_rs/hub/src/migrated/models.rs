#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PlanEventKind {
    #[default]
    Issued,
    Superseded,
    Reported,
}

impl PlanEventKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Issued => "issued",
            Self::Superseded => "superseded",
            Self::Reported => "reported",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfigurationRevision {
    pub digest: String,
    pub body: String,
    pub imported_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfigurationKeyRequest {
    pub digest: String,
    pub installation_id: String,
    pub request_id: String,
    pub payload: String,
    pub identity_proof: String,
    pub signer_proof: String,
    pub requested_by: String,
    pub recorded_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfigurationKeyBinding {
    pub installation_id: String,
    pub version: String,
    pub request_digest: String,
    pub approved_by: String,
    pub approved_at: String,
    pub revoked_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfigurationPlanTrust {
    pub plan_id: String,
    pub installation_id: String,
    pub binding_version: String,
    pub request_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Installation {
    pub installation_id: String,
    pub enrollment: String,
    pub installation_key: String,
    pub settings: String,
    pub suppressions: String,
    pub configuration_digest: String,
    pub last_sequence: String,
    pub requested_at: String,
    pub enrolled_at: String,
    pub recorded_at: String,
    pub configuration: String,
    pub entities: String,
    pub state_reports: String,
    pub evaluations: String,
    pub plans: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Entity {
    pub installation_id: String,
    pub entity_id: String,
    pub kind: String,
    pub ownership: String,
    pub settings: String,
    pub recorded_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StateReport {
    pub id: String,
    pub installation_id: String,
    pub digest: String,
    pub schema_revision: String,
    pub observed_at: String,
    pub recorded_at: String,
    pub available_artifact_digests: String,
    pub entity_states: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EntityReportedState {
    pub report_id: String,
    pub installation_id: String,
    pub entity_id: String,
    pub release_id: String,
    pub artifact_digests: String,
    pub health: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PlanEvaluation {
    pub id: String,
    pub installation_id: String,
    pub outcome: String,
    pub target_release_id: String,
    pub plan_id: String,
    pub evaluated_at: String,
    pub results: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PlanConstraintResult {
    pub id: String,
    pub evaluation_id: String,
    pub release_id: String,
    pub reason_code: String,
    pub details: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Plan {
    pub plan_id: String,
    pub installation_id: String,
    pub sequence: String,
    pub plan_type: String,
    pub target_release_id: String,
    pub source_state_digest: String,
    pub configuration_digest: String,
    pub hub_key_id: String,
    pub entity_ids: String,
    pub signed_payload: String,
    pub signature: String,
    pub issued_at: String,
    pub expires_at: String,
    pub events: String,
    pub reports: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PlanEvent {
    pub id: String,
    pub plan_id: String,
    pub kind: String,
    pub recorded_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PlanReport {
    pub id: String,
    pub plan_id: String,
    pub attempt: String,
    pub outcome: String,
    pub reason_code: String,
    pub exact_plan_digest: String,
    pub summary: String,
    pub reported_at: String,
    pub received_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuditRecord {
    pub sequence: String,
    pub recorded_at: String,
    pub action: String,
    pub installation_id: String,
    pub subject: String,
    pub payload: String,
    pub previous_hash: String,
    pub record_hash: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct UtcDateTime {
    pub initialized: bool,
}

impl UtcDateTime {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn process_bind_param(&self, mut value: Option<String>, mut dialect: String) -> Result<Option<String>, &'static str> {
        let Some(mut value) = value.clone() else { return Ok(None); };
        Ok(None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn process_result_value(&self, mut value: Option<String>, mut dialect: String) -> Option<String> {
        let Some(mut value) = value.clone() else { return None; };
        None
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Base {
    pub initialized: bool,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn stale_tables(mut engine: String) -> Vec<String> {
    if engine.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

