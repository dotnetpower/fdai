#[derive(Clone, Debug, Default, PartialEq)]
pub struct IncidentCreationProposal {
    pub requested_by: String,
    pub correlation_keys: Vec<String>,
    pub severity: String,
    pub source_text: String,
    pub requested_at: String,
    pub expires_at: String,
}

impl IncidentCreationProposal {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.requested_by.trim().is_empty() { return Err("requested_by must be non-empty"); }
        if self.severity.trim().is_empty() { return Err("severity must be non-empty"); }
        if self.source_text.trim().is_empty() { return Err("source_text must be non-empty"); }
        if self.requested_at.trim().is_empty() { return Err("requested_at must be non-empty"); }
        if self.expires_at.trim().is_empty() { return Err("expires_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IncidentChatTurn {
    pub status: String,
    pub response: String,
    #[allow(clippy::type_complexity)]
    pub proposal: Option<Box<IncidentCreationProposal>>,
}

impl IncidentChatTurn {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.status.as_str(), "not_incident" | "needs_details" | "awaiting_confirmation") { return Err("invalid status literal"); }
        Ok(())
    }
}

pub const INCIDENT_TERMS: &[&str] = &["incident", "case", "인시던트", "케이스", "장애"];
pub const RESOURCE_TOKEN: &str = "\\b[a-z0-9][a-z0-9._:/-]{2,199}\\b";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn prepare_incident_chat(mut text: String, mut requested_by: String, mut now: Option<String>, mut confirmation_ttl: String) -> IncidentChatTurn {
    let normalized: String = (text.trim().to_string()).to_lowercase();
    let severity: Option<String> = severity_of(normalized.clone());
    let correlation_keys: Vec<String> = correlation_keys_of(normalized.clone());
    let mut missing: Vec<String> = Vec::<String>::new();
    if severity.is_none() {
        missing.push(String::from("severity"));
    }
    if (correlation_keys.clone()).is_empty() {
        missing.push(String::from("target"));
    }
    if !(missing.clone()).is_empty() {
        let fields: String = (missing.clone()).join(", ");
        return IncidentChatTurn { status: String::from("needs_details"), ..Default::default() };
    }
    let proposal: IncidentCreationProposal = IncidentCreationProposal { requested_by: requested_by.clone(), correlation_keys: correlation_keys.clone(), source_text: text.clone(), ..Default::default() };
    let targets: String = (correlation_keys.clone()).join(", ");
    IncidentChatTurn { status: String::from("awaiting_confirmation"), proposal: Some(Box::new(proposal.clone())), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn severity_of(mut text: String) -> Option<String> {
    if text.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn correlation_keys_of(mut text: String) -> Vec<String> {
    let mut candidates: Vec<String> = Vec::<String>::new();
    Vec::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["IncidentChatStatus", "IncidentChatTurn", "IncidentCreationProposal", "prepare_incident_chat"];
