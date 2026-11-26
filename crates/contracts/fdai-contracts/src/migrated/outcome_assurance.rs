#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OutcomeAssuranceReadState {
    #[default]
    Complete,
    Stale,
    Unavailable,
}

impl OutcomeAssuranceReadState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Complete => "complete",
            Self::Stale => "stale",
            Self::Unavailable => "unavailable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OutcomeAssuranceUnavailableReason {
    #[default]
    SourceNotConnected,
    SourceMissing,
    SourceStale,
    ProjectionMissing,
    ProjectionMalformed,
    PrincipalScopeEmpty,
    InsufficientSample,
}

impl OutcomeAssuranceUnavailableReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::SourceNotConnected => "source_not_connected",
            Self::SourceMissing => "source_missing",
            Self::SourceStale => "source_stale",
            Self::ProjectionMissing => "projection_missing",
            Self::ProjectionMalformed => "projection_malformed",
            Self::PrincipalScopeEmpty => "principal_scope_empty",
            Self::InsufficientSample => "insufficient_sample",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OutcomeAssuranceVertical {
    #[default]
    Resilience,
    ChangeSafety,
    CostGovernance,
}

impl OutcomeAssuranceVertical {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Resilience => "resilience",
            Self::ChangeSafety => "change_safety",
            Self::CostGovernance => "cost_governance",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OutcomeAssuranceSourceState {
    #[default]
    Complete,
    Stale,
    Unavailable,
}

impl OutcomeAssuranceSourceState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Complete => "complete",
            Self::Stale => "stale",
            Self::Unavailable => "unavailable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OutcomeAssuranceReadinessFacet {
    #[default]
    Platform,
    Evidence,
    Detection,
    ActionSafety,
    OperationalHandoff,
    Measurement,
    Promotion,
}

impl OutcomeAssuranceReadinessFacet {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Platform => "platform",
            Self::Evidence => "evidence",
            Self::Detection => "detection",
            Self::ActionSafety => "action_safety",
            Self::OperationalHandoff => "operational_handoff",
            Self::Measurement => "measurement",
            Self::Promotion => "promotion",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OutcomeAssuranceReadinessState {
    #[default]
    Unknown,
    Blocked,
    Observed,
    Ready,
    Stale,
    Unavailable,
}

impl OutcomeAssuranceReadinessState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Unknown => "unknown",
            Self::Blocked => "blocked",
            Self::Observed => "observed",
            Self::Ready => "ready",
            Self::Stale => "stale",
            Self::Unavailable => "unavailable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OutcomeAssuranceAttributionState {
    #[default]
    Unattributed,
    Partial,
    Attributed,
    Unavailable,
}

impl OutcomeAssuranceAttributionState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Unattributed => "unattributed",
            Self::Partial => "partial",
            Self::Attributed => "attributed",
            Self::Unavailable => "unavailable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OutcomeAssuranceMetricState {
    #[default]
    Measured,
    Stale,
    Unavailable,
    InsufficientSample,
    Regressed,
}

impl OutcomeAssuranceMetricState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Measured => "measured",
            Self::Stale => "stale",
            Self::Unavailable => "unavailable",
            Self::InsufficientSample => "insufficient_sample",
            Self::Regressed => "regressed",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OutcomeAssuranceGuardState {
    #[default]
    Unknown,
    Healthy,
    Attention,
    Blocked,
    Stale,
    Unavailable,
}

impl OutcomeAssuranceGuardState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Unknown => "unknown",
            Self::Healthy => "healthy",
            Self::Attention => "attention",
            Self::Blocked => "blocked",
            Self::Stale => "stale",
            Self::Unavailable => "unavailable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OutcomeAssuranceScope {
    pub scope_ref: String,
    pub service_refs: Vec<String>,
    pub workload_refs: Vec<String>,
    pub vertical: Option<OutcomeAssuranceVertical>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OutcomeAssuranceWindow {
    pub start: String,
    pub end: String,
    pub label: Option<String>,
    pub scenario_set_version: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OutcomeAssuranceSource {
    pub name: String,
    pub state: OutcomeAssuranceSourceState,
    pub reason: Option<OutcomeAssuranceUnavailableReason>,
    pub observed_at: Option<String>,
    pub expires_at: Option<String>,
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OutcomeAssuranceReadiness {
    pub facet: OutcomeAssuranceReadinessFacet,
    pub state: OutcomeAssuranceReadinessState,
    pub reason: Option<OutcomeAssuranceUnavailableReason>,
    pub observed_at: Option<String>,
    pub expires_at: Option<String>,
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OutcomeAssuranceAttribution {
    pub state: OutcomeAssuranceAttributionState,
    pub finalized_events: i64,
    pub attributed_events: i64,
    pub unattributed_events: i64,
    pub coverage: Option<f64>,
    pub objective_refs: Vec<String>,
    pub workflow_refs: Vec<String>,
    pub action_type_ids: Vec<String>,
    pub evidence_refs: Vec<String>,
    pub reason: Option<OutcomeAssuranceUnavailableReason>,
}

impl OutcomeAssuranceAttribution {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(0_i64..=9223372036854775807_i64).contains(&self.finalized_events) { return Err("finalized_events out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.attributed_events) { return Err("attributed_events out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.unattributed_events) { return Err("unattributed_events out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OutcomeAssuranceConfidenceInterval {
    pub low: f64,
    pub high: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OutcomeAssuranceMetric {
    pub objective_ref: String,
    pub metric: String,
    pub state: OutcomeAssuranceMetricState,
    pub reason: Option<OutcomeAssuranceUnavailableReason>,
    pub current_value: Option<f64>,
    pub baseline_value: Option<f64>,
    pub target_value: Option<f64>,
    pub unit: Option<String>,
    pub sample_size: Option<i64>,
    #[allow(clippy::type_complexity)]
    pub confidence_interval: Option<Box<OutcomeAssuranceConfidenceInterval>>,
    pub source_time: Option<String>,
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OutcomeAssuranceGuardEvaluation {
    pub guard_id: String,
    pub threshold: f64,
    pub observed_value: f64,
    pub passed: bool,
    pub evidence_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OutcomeAssuranceControlSummary {
    pub state: OutcomeAssuranceGuardState,
    pub reason: Option<OutcomeAssuranceUnavailableReason>,
    pub guard_evaluations: Vec<OutcomeAssuranceGuardEvaluation>,
    pub policy_escape_count: i64,
    pub evidence_refs: Vec<String>,
}

impl OutcomeAssuranceControlSummary {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(0_i64..=9223372036854775807_i64).contains(&self.policy_escape_count) { return Err("policy_escape_count out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OutcomeAssuranceProvenance {
    pub as_of: String,
    pub generated_at: String,
    pub source_names: Vec<String>,
    pub synthetic: bool,
}

impl OutcomeAssuranceProvenance {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.synthetic { return Err("synthetic violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OutcomeAssuranceProjection {
    pub r#type: String,
    pub schema_version: String,
    pub state: OutcomeAssuranceReadState,
    pub reason: Option<OutcomeAssuranceUnavailableReason>,
    pub scope: Box<OutcomeAssuranceScope>,
    pub window: Box<OutcomeAssuranceWindow>,
    pub sources: Vec<OutcomeAssuranceSource>,
    pub readiness: Vec<OutcomeAssuranceReadiness>,
    pub alignment: Box<OutcomeAssuranceAttribution>,
    pub outcomes: Vec<OutcomeAssuranceMetric>,
    pub guards: Box<OutcomeAssuranceControlSummary>,
    pub provenance: Box<OutcomeAssuranceProvenance>,
    pub principal_scoped: bool,
    pub execution_authority: bool,
    pub approval_authority: bool,
    pub promotion_authority: bool,
}

impl OutcomeAssuranceProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.r#type.as_str(), "outcome-assurance.projection") { return Err("invalid type literal"); }
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !self.principal_scoped { return Err("principal_scoped violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.approval_authority { return Err("approval_authority violated literal bool invariant"); }
        if self.promotion_authority { return Err("promotion_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl OutcomeAssuranceScope {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn require_unique_refs(mut value: Vec<String>) -> Result<Vec<String>, &'static str> {
        if (((value.clone()).len() as i64)) != ((((value.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
            return Err("Outcome Assurance scope refs MUST be unique");
        }
        Ok(value.clone())
    }
}

impl OutcomeAssuranceWindow {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_timezone(mut value: String) -> Result<String, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_window(&self) -> Result<OutcomeAssuranceWindow, &'static str> {
        if (self.end.clone()) <= (self.start.clone()) {
            return Err("Outcome Assurance window end MUST follow start");
        }
        Ok(self.clone())
    }
}

impl OutcomeAssuranceSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn require_optional_timezone(mut value: Option<String>) -> Result<Option<String>, &'static str> {
        let Some(mut value) = value.clone() else { return Ok(None); };
        Ok(None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_source(&self) -> Result<OutcomeAssuranceSource, &'static str> {
        if (((self.evidence_refs.clone()).len() as i64)) != ((((self.evidence_refs.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
            return Err("Outcome Assurance source evidence refs MUST be unique");
        }
        if (self.observed_at.is_none()) != (self.expires_at.is_none()) {
            return Err("Outcome Assurance source freshness requires both timestamps");
        }
        if (self.observed_at.is_some()) && (self.expires_at.is_some()) {
            if ((self.expires_at.clone()).unwrap_or_default()) <= ((self.observed_at.clone()).unwrap_or_default()) {
                return Err("Outcome Assurance source expiry MUST follow observation");
            }
        }
        Ok(self.clone())
    }
}

impl OutcomeAssuranceReadiness {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn require_optional_timezone(mut value: Option<String>) -> Result<Option<String>, &'static str> {
        let Some(mut value) = value.clone() else { return Ok(None); };
        Ok(None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_readiness(&self) -> Result<OutcomeAssuranceReadiness, &'static str> {
        if (((self.evidence_refs.clone()).len() as i64)) != ((((self.evidence_refs.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
            return Err("Outcome Assurance readiness evidence refs MUST be unique");
        }
        if (self.observed_at.is_none()) != (self.expires_at.is_none()) {
            return Err("Outcome Assurance readiness freshness requires both timestamps");
        }
        if (self.observed_at.is_some()) && (self.expires_at.is_some()) {
            if ((self.expires_at.clone()).unwrap_or_default()) <= ((self.observed_at.clone()).unwrap_or_default()) {
                return Err("Outcome Assurance readiness expiry MUST follow observation");
            }
        }
        Ok(self.clone())
    }
}

impl OutcomeAssuranceAttribution {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_attribution(&self) -> Result<OutcomeAssuranceAttribution, &'static str> {
        if (self.finalized_events) != ((self.attributed_events).saturating_add(self.unattributed_events)) {
            return Err("finalized_events MUST equal attributed_events  unattributed_events");
        }
        if self.reason.is_some() {
            return Err("available attribution cannot carry an unavailable reason");
        }
        if ((self.attributed_events) > (0_i64)) && (((self.evidence_refs.clone()).is_empty()) || ((self.objective_refs.clone()).is_empty())) {
            return Err("attributed Outcome Assurance events MUST cite objective evidence");
        }
        Ok(self.clone())
    }
}

impl OutcomeAssuranceConfidenceInterval {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_interval(&self) -> Result<OutcomeAssuranceConfidenceInterval, &'static str> {
        if (self.high) < (self.low) {
            return Err("Outcome Assurance confidence interval high MUST be  low");
        }
        Ok(self.clone())
    }
}

impl OutcomeAssuranceMetric {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn require_optional_timezone(mut value: Option<String>) -> Result<Option<String>, &'static str> {
        let Some(mut value) = value.clone() else { return Ok(None); };
        Ok(None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_metric(&self) -> Result<OutcomeAssuranceMetric, &'static str> {
        if (((self.evidence_refs.clone()).len() as i64)) != ((((self.evidence_refs.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
            return Err("Outcome Assurance metric evidence refs MUST be unique");
        }
        Ok(self.clone())
    }
}

impl OutcomeAssuranceControlSummary {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_control_summary(&self) -> Result<OutcomeAssuranceControlSummary, &'static str> {
        if (((self.evidence_refs.clone()).len() as i64)) != ((((self.evidence_refs.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
            return Err("Outcome Assurance guard evidence refs MUST be unique");
        }
        if self.reason.is_some() {
            return Err("available guards cannot carry an unavailable reason");
        }
        Ok(self.clone())
    }
}

impl OutcomeAssuranceProvenance {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_timezone(mut value: String) -> Result<String, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_provenance(&self) -> Result<OutcomeAssuranceProvenance, &'static str> {
        if (self.generated_at.clone()) < (self.as_of.clone()) {
            return Err("Outcome Assurance generated_at MUST NOT precede as_of");
        }
        if (((self.source_names.clone()).len() as i64)) != ((((self.source_names.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
            return Err("Outcome Assurance provenance source names MUST be unique");
        }
        Ok(self.clone())
    }
}

impl OutcomeAssuranceProjection {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_projection(&self) -> Result<OutcomeAssuranceProjection, &'static str> {
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["OutcomeAssuranceAttribution", "OutcomeAssuranceAttributionState", "OutcomeAssuranceConfidenceInterval", "OutcomeAssuranceControlSummary", "OutcomeAssuranceGuardEvaluation", "OutcomeAssuranceGuardState", "OutcomeAssuranceMetric", "OutcomeAssuranceMetricState", "OutcomeAssuranceProjection", "OutcomeAssuranceProvenance", "OutcomeAssuranceReadState", "OutcomeAssuranceReadiness", "OutcomeAssuranceReadinessFacet", "OutcomeAssuranceReadinessState", "OutcomeAssuranceScope", "OutcomeAssuranceSource", "OutcomeAssuranceSourceState", "OutcomeAssuranceUnavailableReason", "OutcomeAssuranceVertical", "OutcomeAssuranceWindow"];
