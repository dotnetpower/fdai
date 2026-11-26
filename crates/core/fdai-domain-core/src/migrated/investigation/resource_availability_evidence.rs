#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ResourceOperationalState {
    #[default]
    Running,
    Stopped,
    Unknown,
}

impl ResourceOperationalState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Running => "running",
            Self::Stopped => "stopped",
            Self::Unknown => "unknown",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AvailabilityUnavailableReason {
    #[default]
    SourceUnavailable,
    AuthorizationDenied,
    ResourceMissing,
    IdentityMismatch,
    GenerationChanged,
    UnsupportedResourceType,
    ObservationIncomplete,
}

impl AvailabilityUnavailableReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::SourceUnavailable => "source_unavailable",
            Self::AuthorizationDenied => "authorization_denied",
            Self::ResourceMissing => "resource_missing",
            Self::IdentityMismatch => "identity_mismatch",
            Self::GenerationChanged => "generation_changed",
            Self::UnsupportedResourceType => "unsupported_resource_type",
            Self::ObservationIncomplete => "observation_incomplete",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PlannedStopWindow {
    pub resource_ref: String,
    pub since: String,
    pub until: String,
    pub evidence_ref: String,
    pub maintenance: bool,
}

impl PlannedStopWindow {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.resource_ref.trim().is_empty() { return Err("resource_ref must be non-empty"); }
        if self.since.trim().is_empty() { return Err("since must be non-empty"); }
        if self.until.trim().is_empty() { return Err("until must be non-empty"); }
        if self.evidence_ref.trim().is_empty() { return Err("evidence_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceAvailabilityPolicy {
    pub resource_types: Vec<String>,
    pub expected_state: Option<ResourceOperationalState>,
    pub expectation_ref: Option<String>,
    pub planned_stops: Vec<PlannedStopWindow>,
    pub max_age_seconds: f64,
}

impl ResourceAvailabilityPolicy {
    pub fn validate(&self) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceAvailabilityEvidence {
    pub resource_ref: String,
    pub resource_type: String,
    pub scope_ref: String,
    pub state: ResourceOperationalState,
    pub observed_at: Option<String>,
    pub recorded_at: String,
    pub source_revision: Option<String>,
    pub evidence_ref: Option<String>,
    pub unavailable_reason: Option<AvailabilityUnavailableReason>,
    pub state_metadata: Option<String>,
}

impl ResourceAvailabilityEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.resource_ref.trim().is_empty() { return Err("resource_ref must be non-empty"); }
        if self.resource_type.trim().is_empty() { return Err("resource_type must be non-empty"); }
        if self.scope_ref.trim().is_empty() { return Err("scope_ref must be non-empty"); }
        if self.recorded_at.trim().is_empty() { return Err("recorded_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceAvailabilityAssessment {
    pub evidence_complete: bool,
    pub recovery_closed: Option<bool>,
    pub status: String,
    pub recovery_status: Option<String>,
    pub evidence_gaps: Vec<String>,
}

impl ResourceAvailabilityAssessment {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.status.trim().is_empty() { return Err("status must be non-empty"); }
        Ok(())
    }
}

pub const RESOURCE_AVAILABILITY_ASSESSOR: &str = "core.investigation.resource_availability_evidence";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_aware(mut value: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::too_many_arguments)]
pub fn assess_resource_availability(mut evidence: ResourceAvailabilityEvidence, mut resource_ref: String, mut resource_type: String, mut scope_ref: String, mut since: String, mut until: String, mut policy: ResourceAvailabilityPolicy, mut prior_status: Option<String>, mut prior_fault_at: Option<String>, mut prior_finding_ref: Option<String>) -> Result<ResourceAvailabilityAssessment, &'static str> {
    let _ = require_aware(since.clone()).unwrap_or_else(|_| ());
    let _ = require_aware(until.clone()).unwrap_or_else(|_| ());
    if (since.clone()) >= (until.clone()) {
        return Err("availability window MUST be positive");
    }
    if let Some(mut prior_fault_at) = prior_fault_at.clone() {
        let _ = require_aware(prior_fault_at.clone()).unwrap_or_else(|_| ());
    }
    let mut gap: Option<String> = None;
    if !((policy.resource_types.clone()).contains(&(resource_type.clone()))) {
        gap = Some(String::from("not_monitored"));
    } else if (!((evidence.source_revision.clone()).is_some())) || (!((evidence.evidence_ref.clone()).is_some())) {
        gap = Some(String::from("provenance_missing"));
    } else if (evidence.observed_at.clone()).is_none() {
        gap = Some(String::from("observation_time_missing"));
    } else if (((evidence.observed_at.clone()).unwrap_or_default()) > (until.clone())) || (((evidence.observed_at.clone()).unwrap_or_default()) > (evidence.recorded_at.clone())) {
        gap = Some(String::from("observation_time_invalid"));
    }
    if let Some(mut gap) = gap.clone() {
        return Ok(ResourceAvailabilityAssessment { evidence_complete: false, recovery_closed: None, status: gap.clone(), ..Default::default() });
    }
    let recovery_pairs: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("stop_observed"), String::from("running_observed")), (String::from("expected_running_not_observed"), String::from("running_observed")), (String::from("expected_stop_not_observed"), String::from("expected_stop_observed"))]);
    Ok(ResourceAvailabilityAssessment { evidence_complete: true, recovery_status: Some(String::from("expected_state_observed\" if recovered else \"not_verified")), ..Default::default() })
}

