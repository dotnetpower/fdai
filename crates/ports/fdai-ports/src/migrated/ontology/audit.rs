#[derive(Clone, Debug, Default, PartialEq)]
pub struct RedactedFieldRecord {
    pub property: String,
    pub reason: String,
    pub required_role: Option<String>,
    pub required_purposes: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProjectionAuditEvent {
    pub audit_id: String,
    pub observed_at: String,
    pub caller_id: String,
    pub caller_role: String,
    pub declared_purposes: Vec<String>,
    pub surface: String,
    pub object_type: String,
    pub instance_key: Option<String>,
    pub redactions: Vec<RedactedFieldRecord>,
    pub correlation_id: Option<String>,
}

impl ProjectionAuditEvent {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::too_many_arguments)]
    pub fn make(mut audit_id: String, mut caller_id: String, mut caller_role: String, mut declared_purposes: std::collections::BTreeSet<String>, mut surface: String, mut object_type: String, mut instance_key: Option<String>, mut redactions: Vec<RedactedFieldRecord>, mut correlation_id: Option<String>) -> ProjectionAuditEvent {
        if audit_id.is_empty() {
            return Default::default();
        }
        Default::default()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProjectionAuditEvent", "RedactedFieldRecord"];
