#[derive(Clone, Debug, Default, PartialEq)]
pub struct Incident {
    pub schema_version: String,
    pub incident_id: String,
    pub incident_number: Option<String>,
    pub state: String,
    pub severity: String,
    pub opened_at: String,
    pub mitigated_at: Option<String>,
    pub resolved_at: Option<String>,
    pub closed_at: Option<String>,
    pub correlation_keys: Vec<String>,
    pub member_event_ids: Vec<String>,
    pub related_finding_ids: Vec<String>,
    pub related_action_ids: Vec<String>,
    pub assignee_oid: Option<String>,
    pub mitigation_summary: Option<String>,
    pub postmortem_ref: Option<String>,
}

pub const INCIDENT_NUMBER_PATTERN: &str = "^INC-\\d{6}-\\d{4}$";
impl Incident {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn list_to_tuple(mut v: String) -> String {
        v.clone()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["Incident"];
