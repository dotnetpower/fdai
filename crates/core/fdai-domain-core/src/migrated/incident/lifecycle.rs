#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum IncidentNoticeKind {
    #[default]
    Opened,
    SeverityChanged,
    StateChanged,
    Roster,
    SlaBreach,
    Assigned,
}

impl IncidentNoticeKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Opened => "opened",
            Self::SeverityChanged => "severity_changed",
            Self::StateChanged => "state_changed",
            Self::Roster => "roster",
            Self::SlaBreach => "sla_breach",
            Self::Assigned => "assigned",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IncidentLifecycleNotice {
    pub kind: IncidentNoticeKind,
    pub actor_oid: String,
    pub occurred_at: String,
    pub incident: Option<String>,
    pub incident_id: Option<String>,
    pub incident_state: Option<String>,
    pub incident_severity: Option<String>,
    pub previous_state: Option<String>,
    pub previous_severity: Option<String>,
    pub reason: Option<String>,
    pub roster: Vec<String>,
}

impl IncidentLifecycleNotice {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.actor_oid.trim().is_empty() { return Err("actor_oid must be non-empty"); }
        if self.occurred_at.trim().is_empty() { return Err("occurred_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IncidentWorkflowResult {
    pub incident: String,
    pub response: String,
    pub notification_result: Option<String>,
    pub created: bool,
    pub changed: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IncidentNotificationDeferred {
    pub error_type: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IncidentRosterResult {
    pub incidents: Vec<String>,
    pub notification_result: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IncidentTicketLink {
    pub incident_id: String,
    pub provider: String,
    pub ticket_id: String,
    pub ticket_url: Option<String>,
    pub linked_at: String,
    pub linked_by: String,
}

impl IncidentTicketLink {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.incident_id.trim().is_empty() { return Err("incident_id must be non-empty"); }
        if self.provider.trim().is_empty() { return Err("provider must be non-empty"); }
        if self.ticket_id.trim().is_empty() { return Err("ticket_id must be non-empty"); }
        if self.linked_at.trim().is_empty() { return Err("linked_at must be non-empty"); }
        if self.linked_by.trim().is_empty() { return Err("linked_by must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IncidentWorkflowError {
    pub message: String,
}

impl IncidentWorkflowError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for IncidentWorkflowError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for IncidentWorkflowError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IncidentWorkflowForbiddenError {
    pub message: String,
}

impl IncidentWorkflowForbiddenError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for IncidentWorkflowForbiddenError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for IncidentWorkflowForbiddenError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IncidentConfirmationError {
    pub message: String,
}

impl IncidentConfirmationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for IncidentConfirmationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for IncidentConfirmationError {}

pub trait IncidentLifecycleNotifier {
    fn notify(&self, notice: IncidentLifecycleNotice) -> String;
}

pub trait IncidentOperatorPrincipal {
    fn id(&self) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NullIncidentLifecycleNotifier {
    pub initialized: bool,
}

impl NullIncidentLifecycleNotifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn notify(&self, mut notice: IncidentLifecycleNotice) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["IncidentConfirmationError", "IncidentLifecycleNotice", "IncidentLifecycleNotifier", "IncidentNotificationDeferred", "IncidentNoticeKind", "IncidentOperatorPrincipal", "IncidentRosterResult", "IncidentTicketLink", "IncidentWorkflowError", "IncidentWorkflowForbiddenError", "IncidentWorkflowResult", "NullIncidentLifecycleNotifier"];
