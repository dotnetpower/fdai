#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ApprovalContactConsentState {
    #[default]
    Pending,
    Consented,
    Declined,
}

impl ApprovalContactConsentState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Consented => "consented",
            Self::Declined => "declined",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ApprovalContactConsent {
    pub consent_id: String,
    pub requester_ref: String,
    pub action_digest: String,
    pub route_digest: String,
    pub path_revision: String,
    pub created_at: String,
    pub expires_at: String,
    pub state: ApprovalContactConsentState,
    pub revision: i64,
    pub decided_at: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ApprovalContactConsentService {
    pub store: String,
    pub ttl: String,
}

pub const PREFIX: &str = "human_reporting:approval-consent:";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ApprovalContactConsentExpiredError {
    pub message: String,
}

impl ApprovalContactConsentExpiredError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ApprovalContactConsentExpiredError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ApprovalContactConsentExpiredError {}

impl ApprovalContactConsent {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        let value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("consent_id"), self.consent_id.clone()), (String::from("requester_ref"), self.requester_ref.clone()), (String::from("action_digest"), self.action_digest.clone()), (String::from("route_digest"), self.route_digest.clone()), (String::from("path_revision"), self.path_revision.clone()), (String::from("created_at"), String::new()), (String::from("expires_at"), String::new())]);
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("consent_id"), self.consent_id.clone()), (String::from("requester_ref"), self.requester_ref.clone()), (String::from("action_digest"), self.action_digest.clone()), (String::from("route_digest"), self.route_digest.clone()), (String::from("path_revision"), self.path_revision.clone()), (String::from("created_at"), String::new()), (String::from("expires_at"), String::new()), (String::from("state"), String::new()), (String::from("revision"), String::new()), (String::from("decided_at"), String::new()), (String::from("consent_digest"), String::new()), (String::from("approval_authority"), String::new()), (String::from("execution_authority"), String::new())])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_dict(mut value: std::collections::BTreeMap<String, String>) -> Result<ApprovalContactConsent, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

impl ApprovalContactConsentService {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn request(&self, mut requester_ref: String, mut action_digest: String, mut route_digest: String, mut path_revision: String, mut now: Option<String>) -> Result<ApprovalContactConsent, &'static str> {
        let requested: ApprovalContactConsent = ApprovalContactConsent { action_digest: action_digest.clone(), route_digest: route_digest.clone(), path_revision: path_revision.clone(), ..Default::default() };
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn decide(&self, mut consent_id: String, mut requester_ref: String, mut consent: bool, mut expected_revision: i64, mut now: Option<String>) -> Result<ApprovalContactConsent, &'static str> {
        if consent_id.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut consent_id: String) -> Result<ApprovalContactConsent, &'static str> {
        if consent_id.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ApprovalContactConsent", "ApprovalContactConsentExpiredError", "ApprovalContactConsentService", "ApprovalContactConsentState"];
