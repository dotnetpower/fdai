#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostGovernanceUnavailableReason {
    #[default]
    PackageAbsent,
    PackageDisabled,
    PackageIncompatible,
    HostIncompatible,
    OntologyIncompatible,
    MissingProvider,
    AccessGrantMissing,
    AccessGrantExpired,
    AccessScopeMismatch,
    SourceUnavailable,
}

impl CostGovernanceUnavailableReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::PackageAbsent => "package_absent",
            Self::PackageDisabled => "package_disabled",
            Self::PackageIncompatible => "package_incompatible",
            Self::HostIncompatible => "host_incompatible",
            Self::OntologyIncompatible => "ontology_incompatible",
            Self::MissingProvider => "missing_provider",
            Self::AccessGrantMissing => "access_grant_missing",
            Self::AccessGrantExpired => "access_grant_expired",
            Self::AccessScopeMismatch => "access_scope_mismatch",
            Self::SourceUnavailable => "source_unavailable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostGranularity {
    #[default]
    None,
    Summary,
    Group,
    Resource,
}

impl CostGranularity {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Summary => "summary",
            Self::Group => "group",
            Self::Resource => "resource",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostIdentityVisibility {
    #[default]
    None,
    Pseudonymous,
    Exact,
}

impl CostIdentityVisibility {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Pseudonymous => "pseudonymous",
            Self::Exact => "exact",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostAmountPrecision {
    #[default]
    None,
    Band,
    Rounded,
    Exact,
}

impl CostAmountPrecision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Band => "band",
            Self::Rounded => "rounded",
            Self::Exact => "exact",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostEvidenceFreshness {
    #[default]
    Fresh,
    Stale,
    Unknown,
}

impl CostEvidenceFreshness {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Fresh => "fresh",
            Self::Stale => "stale",
            Self::Unknown => "unknown",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostEvidenceState {
    #[default]
    Complete,
    Partial,
    Unavailable,
}

impl CostEvidenceState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Complete => "complete",
            Self::Partial => "partial",
            Self::Unavailable => "unavailable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostReadinessReason {
    #[default]
    NoObservations,
    ObservationsPartial,
    ObservationsStale,
    AnalyticsRunMissing,
    AnalyticsRunFailed,
    AnalyticsRunPartial,
    AnalyticsDisabled,
    AnalyticsSnapshotMissing,
    AnalyticsStale,
    DisclosureInsufficient,
    ResourceCandidatesMissing,
    CandidateEvidenceIncomplete,
    DecisionCasesMissing,
    DecisionCaseIncomplete,
    SettlementsMissing,
    SettlementIncomplete,
    ProjectionTruncated,
}

impl CostReadinessReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::NoObservations => "no_observations",
            Self::ObservationsPartial => "observations_partial",
            Self::ObservationsStale => "observations_stale",
            Self::AnalyticsRunMissing => "analytics_run_missing",
            Self::AnalyticsRunFailed => "analytics_run_failed",
            Self::AnalyticsRunPartial => "analytics_run_partial",
            Self::AnalyticsDisabled => "analytics_disabled",
            Self::AnalyticsSnapshotMissing => "analytics_snapshot_missing",
            Self::AnalyticsStale => "analytics_stale",
            Self::DisclosureInsufficient => "disclosure_insufficient",
            Self::ResourceCandidatesMissing => "resource_candidates_missing",
            Self::CandidateEvidenceIncomplete => "candidate_evidence_incomplete",
            Self::DecisionCasesMissing => "decision_cases_missing",
            Self::DecisionCaseIncomplete => "decision_case_incomplete",
            Self::SettlementsMissing => "settlements_missing",
            Self::SettlementIncomplete => "settlement_incomplete",
            Self::ProjectionTruncated => "projection_truncated",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostAnalyticsRunStatus {
    #[default]
    Complete,
    Partial,
    Failed,
    Disabled,
}

impl CostAnalyticsRunStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Complete => "complete",
            Self::Partial => "partial",
            Self::Failed => "failed",
            Self::Disabled => "disabled",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostDisclosurePolicy {
    pub granularity: CostGranularity,
    pub identity_visibility: CostIdentityVisibility,
    pub amount_precision: CostAmountPrecision,
    pub small_cell_minimum: i64,
    pub rounding_increment: i64,
}

impl CostDisclosurePolicy {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=100_i64).contains(&self.small_cell_minimum) { return Err("small_cell_minimum out of bounds"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.rounding_increment) { return Err("rounding_increment out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostEvidenceSourceFacet {
    pub source_authority: String,
    pub state: CostEvidenceState,
    pub window_start_at: Option<String>,
    pub window_end_at: Option<String>,
    pub latest_source_at: Option<String>,
    pub complete_count: i64,
    pub partial_count: i64,
    pub reason: Option<String>,
}

impl CostEvidenceSourceFacet {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(0_i64..=9223372036854775807_i64).contains(&self.complete_count) { return Err("complete_count out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.partial_count) { return Err("partial_count out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostAnalyticsRunReceipt {
    pub r#type: String,
    pub schema_version: String,
    pub run_id: String,
    pub receipt_digest: String,
    pub scope_digest: String,
    pub venue: String,
    pub window_start_at: String,
    pub window_end_at: String,
    pub started_at: String,
    pub finished_at: String,
    pub status: CostAnalyticsRunStatus,
    pub sources: Vec<CostEvidenceSourceFacet>,
    pub observation_count: i64,
    pub trend_point_count: i64,
    pub budget_count: i64,
    pub recommendation_count: i64,
    pub utilization_count: i64,
    pub limitations: Vec<String>,
    pub failure_reason: Option<String>,
    pub snapshot_id: Option<String>,
}

impl CostAnalyticsRunReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.r#type.as_str(), "cost-governance.analytics-run") { return Err("invalid type literal"); }
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.venue.as_str(), "local" | "deployed") { return Err("invalid venue literal"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.observation_count) { return Err("observation_count out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.trend_point_count) { return Err("trend_point_count out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.budget_count) { return Err("budget_count out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.recommendation_count) { return Err("recommendation_count out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.utilization_count) { return Err("utilization_count out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostSurfaceReadiness {
    pub surface: String,
    pub state: CostEvidenceState,
    pub reason: Option<CostReadinessReason>,
    pub record_count: i64,
    pub returned_count: i64,
    pub truncated: bool,
    pub latest_evidence_at: Option<String>,
}

impl CostSurfaceReadiness {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.surface.as_str(), "observations" | "analytics" | "resource-candidates" | "decision-cases" | "settlements") { return Err("invalid surface literal"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.record_count) { return Err("record_count out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.returned_count) { return Err("returned_count out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostProjectionEvidence {
    pub window_start_at: Option<String>,
    pub window_end_at: Option<String>,
    pub latest_source_at: Option<String>,
    pub freshness: CostEvidenceFreshness,
    pub freshness_threshold_seconds: i64,
    pub complete_count: i64,
    pub partial_count: i64,
    pub sources: Vec<CostEvidenceSourceFacet>,
    pub disclosure: Box<CostDisclosurePolicy>,
    pub readiness: Vec<CostSurfaceReadiness>,
    #[allow(clippy::type_complexity)]
    pub latest_analytics_run: Option<Box<CostAnalyticsRunReceipt>>,
}

impl CostProjectionEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=2592000_i64).contains(&self.freshness_threshold_seconds) { return Err("freshness_threshold_seconds out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.complete_count) { return Err("complete_count out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.partial_count) { return Err("partial_count out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostGovernanceAvailability {
    pub r#type: String,
    pub schema_version: String,
    pub available: bool,
    pub enabled: bool,
    pub access_allowed: bool,
    pub package_id: String,
    pub activation_revision: Option<i64>,
    pub availability_reasons: Vec<String>,
    pub package_version: Option<String>,
    pub image_digest: Option<String>,
    pub asset_manifest_digest: Option<String>,
    pub semantic_profile_digest: Option<String>,
    pub ontology_release_digest: Option<String>,
    pub reason: Option<CostGovernanceUnavailableReason>,
    #[allow(clippy::type_complexity)]
    pub disclosure: Option<Box<CostDisclosurePolicy>>,
}

impl CostGovernanceAvailability {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.r#type.as_str(), "cost-governance.availability") { return Err("invalid type literal"); }
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostAccessGrant {
    pub r#type: String,
    pub schema_version: String,
    pub grant_id: String,
    pub principal_id: String,
    pub revision: i64,
    pub purpose: String,
    pub scopes: Vec<String>,
    pub disclosure: Box<CostDisclosurePolicy>,
    pub effective_at: String,
    pub expires_at: String,
    pub source_authority: String,
}

impl CostAccessGrant {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.grant_id.trim().is_empty() { return Err("grant_id must be non-empty"); }
        if self.principal_id.trim().is_empty() { return Err("principal_id must be non-empty"); }
        if self.purpose.trim().is_empty() { return Err("purpose must be non-empty"); }
        if self.effective_at.trim().is_empty() { return Err("effective_at must be non-empty"); }
        if self.expires_at.trim().is_empty() { return Err("expires_at must be non-empty"); }
        if self.source_authority.trim().is_empty() { return Err("source_authority must be non-empty"); }
        if !matches!(self.r#type.as_str(), "cost-governance.access-grant") { return Err("invalid type literal"); }
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.revision) { return Err("revision out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostDisclosureCeiling {
    pub r#type: String,
    pub schema_version: String,
    pub revision: i64,
    pub disclosure: Box<CostDisclosurePolicy>,
    pub effective_at: String,
    pub source_authority: String,
}

impl CostDisclosureCeiling {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.r#type.as_str(), "cost-governance.disclosure-ceiling") { return Err("invalid type literal"); }
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.revision) { return Err("revision out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostProjectionRecord {
    pub record_id: String,
    pub group_id: String,
    pub resource_id: Option<String>,
    pub service_id: String,
    pub amount: i64,
    pub previous_amount: Option<i64>,
    pub currency: String,
    pub observed_at: String,
    pub window_start_at: Option<String>,
    pub window_end_at: Option<String>,
    pub recorded_at: Option<String>,
    pub completeness: i64,
    pub source_authority: String,
    pub provenance_digest: String,
    pub status: Option<String>,
}

impl CostProjectionRecord {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(0_i64..=9223372036854775807_i64).contains(&self.amount) { return Err("amount out of bounds"); }
        if !(0_i64..=1_i64).contains(&self.completeness) { return Err("completeness out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostDetailedProjection {
    pub record_id: String,
    pub resource: Option<String>,
    pub service_id: String,
    pub currency: String,
    pub observed_at: String,
    pub completeness: i64,
    pub source_authority: String,
    pub provenance_digest: String,
    pub status: Option<String>,
    pub amount_band: Option<String>,
    pub amount_rounded: Option<i64>,
    pub amount_exact: Option<i64>,
    pub relative_change: Option<i64>,
    pub positive_below_rounding_increment: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostSummaryProjection {
    pub kind: String,
    pub group_id: Option<String>,
    pub currency: String,
    pub record_count: i64,
    pub suppressed: bool,
    pub amount_band: Option<String>,
    pub amount_rounded: Option<i64>,
    pub amount_exact: Option<i64>,
    pub positive_below_rounding_increment: bool,
}

impl CostSummaryProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "summary") { return Err("invalid kind literal"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.record_count) { return Err("record_count out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostTrendProjection {
    pub kind: String,
}

impl CostTrendProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "trend") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostResourceEfficiencyProjection {
    pub kind: String,
}

impl CostResourceEfficiencyProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "resource") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostResourceCandidateProjection {
    pub kind: String,
    pub recommendation_ref: String,
    pub resource: String,
    pub resource_type: String,
    pub current_configuration: String,
    pub proposed_configuration: String,
    pub utilization_metric: String,
    pub utilization_percent: i64,
    pub projected_monthly_savings: Option<i64>,
    pub currency: Option<String>,
    pub observed_at: String,
    pub source_authority: String,
}

impl CostResourceCandidateProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "resource_candidate") { return Err("invalid kind literal"); }
        if !(0_i64..=100_i64).contains(&self.utilization_percent) { return Err("utilization_percent out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostOptimizationCaseProjection {
    pub kind: String,
}

impl CostOptimizationCaseProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "optimization_case") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostOutcomeProjection {
    pub kind: String,
}

impl CostOutcomeProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "outcome") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostDecisionCaseProjection {
    pub kind: String,
    pub case_ref: String,
    pub revision: i64,
    pub target_refs: Vec<String>,
    pub evidence_cutoff: String,
    pub decision_frame_digest: String,
    pub option_ids: Vec<String>,
    pub selected_option_id: Option<String>,
    pub verdict: String,
    pub reason: String,
    pub evidence_refs: Vec<String>,
    pub evidence_sources: Vec<String>,
    pub recovery_steps: Vec<String>,
    pub recorded_at: String,
    pub source_authority: String,
}

impl CostDecisionCaseProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "decision_case") { return Err("invalid kind literal"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.revision) { return Err("revision out of bounds"); }
        if !matches!(self.verdict.as_str(), "hold") { return Err("invalid verdict literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostSettlementEffectProjection {
    pub effect_id: String,
    pub kind: String,
    pub status: String,
    pub reason: String,
    pub terminal: bool,
    pub observation_digest: Option<String>,
    pub completeness_digest: Option<String>,
}

impl CostSettlementEffectProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "cost" | "capacity" | "service" | "recovery") { return Err("invalid kind literal"); }
        if !matches!(self.status.as_str(), "verified" | "failed" | "censored" | "unscorable") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostSettlementOutcomeProjection {
    pub kind: String,
    pub case_ref: String,
    pub revision: i64,
    pub action_ref: String,
    pub action_revision: i64,
    pub decision_frame_digest: String,
    pub terminal: bool,
    pub verified_savings: Option<i64>,
    pub currency: Option<String>,
    pub rollback_requested: bool,
    pub recovery_observed: bool,
    pub effects: Vec<CostSettlementEffectProjection>,
    pub settled_at: String,
}

impl CostSettlementOutcomeProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "settlement_outcome") { return Err("invalid kind literal"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.revision) { return Err("revision out of bounds"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.action_revision) { return Err("action_revision out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostAnalyticsTrendPoint {
    pub observed_on: String,
    pub amount: i64,
    pub currency: String,
    pub completeness: i64,
}

impl CostAnalyticsTrendPoint {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(0_i64..=9223372036854775807_i64).contains(&self.amount) { return Err("amount out of bounds"); }
        if !(0_i64..=1_i64).contains(&self.completeness) { return Err("completeness out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostAnalyticsBudget {
    pub budget_ref: String,
    pub amount: i64,
    pub current_spend: i64,
    pub forecast_spend: Option<i64>,
    pub currency: String,
    pub time_grain: String,
}

impl CostAnalyticsBudget {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=9223372036854775807_i64).contains(&self.amount) { return Err("amount out of bounds"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.current_spend) { return Err("current_spend out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostAnalyticsRecommendation {
    pub recommendation_ref: String,
    pub resource_ref: Option<String>,
    pub resource_type: String,
    pub problem: String,
    pub solution: String,
    pub impact: String,
    pub monthly_savings: Option<i64>,
    pub currency: Option<String>,
    pub current_sku: Option<String>,
    pub target_sku: Option<String>,
    pub utilization_percent: Option<i64>,
    pub utilization_metric: Option<String>,
    pub observed_at: String,
    pub source_authority: String,
}

impl CostAnalyticsRecommendation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.impact.as_str(), "High" | "Medium" | "Low" | "Unknown") { return Err("invalid impact literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostAnalyticsProjection {
    pub r#type: String,
    pub schema_version: String,
    pub source_authority: String,
    pub observed_at: String,
    pub complete: bool,
    pub window_start_at: Option<String>,
    pub window_end_at: Option<String>,
    pub sources: Vec<CostEvidenceSourceFacet>,
    pub trend: Vec<CostAnalyticsTrendPoint>,
    pub budgets: Vec<CostAnalyticsBudget>,
    pub recommendations: Vec<CostAnalyticsRecommendation>,
    pub limitations: Vec<String>,
}

impl CostAnalyticsProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.r#type.as_str(), "cost-governance.analytics") { return Err("invalid type literal"); }
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostGovernanceProjection {
    pub r#type: String,
    pub schema_version: String,
    pub surface: String,
    pub disclosure: Box<CostDisclosurePolicy>,
    pub generated_at: String,
    pub source_authority: String,
    pub complete: bool,
    pub items: Vec<CostSummaryProjection>,
    pub suppressed_count: i64,
    #[allow(clippy::type_complexity)]
    pub analytics: Option<Box<CostAnalyticsProjection>>,
    #[allow(clippy::type_complexity)]
    pub evidence: Option<Box<CostProjectionEvidence>>,
    pub resource_efficiency_mode: Option<String>,
}

impl CostGovernanceProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.r#type.as_str(), "cost-governance.projection") { return Err("invalid type literal"); }
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.surface.as_str(), "overview" | "resource-efficiency" | "optimization-cases" | "outcomes") { return Err("invalid surface literal"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.suppressed_count) { return Err("suppressed_count out of bounds"); }
        Ok(())
    }
}

impl CostDisclosurePolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn meet(&self, mut other: CostDisclosurePolicy) -> CostDisclosurePolicy {
        CostDisclosurePolicy { small_cell_minimum: (self.small_cell_minimum).max(other.small_cell_minimum), rounding_increment: (self.rounding_increment).max(other.rounding_increment), ..Default::default() }
    }
}

impl CostEvidenceSourceFacet {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_source_facet(&self) -> Result<CostEvidenceSourceFacet, &'static str> {
        if (self.window_start_at.is_some()) && ((self.window_end_at.is_some()) && (((self.window_end_at.clone()).unwrap_or_default()) < ((self.window_start_at.clone()).unwrap_or_default()))) {
            return Err("Cost Governance evidence window must be ordered");
        }
        Ok(self.clone())
    }
}

impl CostAnalyticsRunReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_run_receipt(&self) -> Result<CostAnalyticsRunReceipt, &'static str> {
        if ((self.window_end_at.clone()) <= (self.window_start_at.clone())) || ((self.finished_at.clone()) < (self.started_at.clone())) {
            return Err("Cost Analytics run windows must be ordered");
        }
        if ((((self.limitations.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.limitations.clone()).len() as i64)) {
            return Err("Cost Analytics run limitations must be unique");
        }
        Ok(self.clone())
    }
}

impl CostSurfaceReadiness {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_readiness(&self) -> Result<CostSurfaceReadiness, &'static str> {
        if (self.returned_count) > (self.record_count) {
            return Err("Cost Governance returned count cannot exceed the full record count");
        }
        Ok(self.clone())
    }
}

impl CostProjectionEvidence {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_projection_evidence(&self) -> Result<CostProjectionEvidence, &'static str> {
        let expected: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("observations"), String::from("analytics"), String::from("resource-candidates"), String::from("decision-cases"), String::from("settlements")]);
        Ok(self.clone())
    }
}

impl CostGovernanceAvailability {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_state(&self) -> Result<CostGovernanceAvailability, &'static str> {
        if (self.available) && (self.reason.is_some()) {
            return Err("available Cost Governance source cannot have an unavailable reason");
        }
        if (self.enabled) && (!(self.available)) {
            return Err("unavailable Cost Governance source cannot be enabled");
        }
        if ((((self.availability_reasons.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.availability_reasons.clone()).len() as i64)) {
            return Err("availability reasons must be unique");
        }
        if (self.available) == (!(self.availability_reasons.clone()).is_empty()) {
            return Err("availability must match empty availability reasons");
        }
        if (!(self.available)) && (self.reason.is_none()) {
            return Err("unavailable Cost Governance source requires a typed reason");
        }
        if (!(self.access_allowed)) && (self.disclosure.is_some()) {
            return Err("denied Cost Governance access cannot disclose a policy");
        }
        Ok(self.clone())
    }
}

impl CostAccessGrant {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_interval(&self) -> Result<CostAccessGrant, &'static str> {
        if (self.expires_at.clone()) <= (self.effective_at.clone()) {
            return Err("Cost Governance grant expiry must follow its effective time");
        }
        Ok(self.clone())
    }
}

impl CostDisclosureCeiling {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_effective_time(&self) -> Result<CostDisclosureCeiling, &'static str> {
        Err("runtime_binding_required")
    }
}

impl CostSettlementEffectProjection {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_independent_evidence(&self) -> Result<CostSettlementEffectProjection, &'static str> {
        if (matches!(self.status.as_str(), "verified" | "failed")) && ((self.observation_digest.is_none()) || (self.completeness_digest.is_none())) {
            return Err("scored settlement requires observation and completeness evidence");
        }
        Ok(self.clone())
    }
}

impl CostSettlementOutcomeProjection {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_verified_savings(&self) -> Result<CostSettlementOutcomeProjection, &'static str> {
        if (self.currency.is_some()) && (self.verified_savings.is_none()) {
            return Err("settlement currency requires verified savings");
        }
        Ok(self.clone())
    }
}

impl CostAnalyticsProjection {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_analytics(&self) -> Result<CostAnalyticsProjection, &'static str> {
        if (self.window_start_at.is_some()) && ((self.window_end_at.is_some()) && (((self.window_end_at.clone()).unwrap_or_default()) <= ((self.window_start_at.clone()).unwrap_or_default()))) {
            return Err("Cost Governance analytics window must be positive");
        }
        if ((((self.limitations.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.limitations.clone()).len() as i64)) {
            return Err("Cost Governance analytics limitations must be unique");
        }
        Ok(self.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn disclose_cost_records(mut records: Vec<CostProjectionRecord>, mut policy: CostDisclosurePolicy, mut pseudonym_key: Option<Vec<u8>>) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
    if records.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn minimum(mut value: String, mut other: String, mut order: Vec<String>) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn identity(mut record: CostProjectionRecord, mut policy: CostDisclosurePolicy, mut key: Option<Vec<u8>>) -> Option<String> {
    let raw: String = (record.resource_id.clone()).unwrap_or_else(|| record.record_id.clone());
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn amount_projection(mut amount: i64, mut policy: CostDisclosurePolicy, mut previous: Option<i64>) -> std::collections::BTreeMap<String, String> {
    let precision: CostAmountPrecision = policy.amount_precision.clone();
    let mut relative: Option<String> = None;
    std::collections::BTreeMap::from([(String::from("amount_exact"), (amount).to_string())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["CostAccessGrant", "CostAmountPrecision", "CostAnalyticsRunReceipt", "CostAnalyticsRunStatus", "CostDecisionCaseProjection", "CostDisclosureCeiling", "CostDisclosurePolicy", "CostEvidenceFreshness", "CostEvidenceSourceFacet", "CostEvidenceState", "CostGovernanceAvailability", "CostGovernanceItem", "CostGovernanceProjection", "CostGovernanceUnavailableReason", "CostGranularity", "CostIdentityVisibility", "CostOptimizationCaseProjection", "CostOutcomeProjection", "CostProjectionEvidence", "CostProjectionRecord", "CostReadinessReason", "CostResourceCandidateProjection", "CostResourceEfficiencyProjection", "CostSettlementEffectProjection", "CostSettlementOutcomeProjection", "CostSummaryProjection", "CostSurfaceReadiness", "CostTrendProjection", "DISCLOSURE_PRESETS", "disclose_cost_records"];
