#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ForecastScoringExclusion {
    #[default]
    InterventionHistoryUnavailable,
    ContextMismatch,
    ExcludedWindow,
    ResourceDeleted,
    InterventionAffected,
    OperationalEvidenceConflicting,
    OperationalEvidenceCrossScope,
    OperationalEvidencePartial,
    OperationalEvidenceReplaySubstituted,
    OperationalEvidenceRevoked,
    OperationalEvidenceStale,
    OperationalEvidenceSyntheticLive,
}

impl ForecastScoringExclusion {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::InterventionHistoryUnavailable => "intervention_history_unavailable",
            Self::ContextMismatch => "context_mismatch",
            Self::ExcludedWindow => "excluded_window",
            Self::ResourceDeleted => "resource_deleted",
            Self::InterventionAffected => "intervention_affected",
            Self::OperationalEvidenceConflicting => "operational_evidence_conflicting",
            Self::OperationalEvidenceCrossScope => "operational_evidence_cross_scope",
            Self::OperationalEvidencePartial => "operational_evidence_partial",
            Self::OperationalEvidenceReplaySubstituted => "operational_evidence_replay_substituted",
            Self::OperationalEvidenceRevoked => "operational_evidence_revoked",
            Self::OperationalEvidenceStale => "operational_evidence_stale",
            Self::OperationalEvidenceSyntheticLive => "operational_evidence_synthetic_live",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ForecastOutcomeLabel {
    #[default]
    TruePositive,
    FalsePositive,
    FalseNegative,
    LateBreach,
    MagnitudeError,
    InterventionCensored,
    Unscorable,
}

impl ForecastOutcomeLabel {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::TruePositive => "true_positive",
            Self::FalsePositive => "false_positive",
            Self::FalseNegative => "false_negative",
            Self::LateBreach => "late_breach",
            Self::MagnitudeError => "magnitude_error",
            Self::InterventionCensored => "intervention_censored",
            Self::Unscorable => "unscorable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TelemetryCompleteness {
    #[default]
    Complete,
    Partial,
    Unavailable,
}

impl TelemetryCompleteness {
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
pub enum ForecastMissOrigin {
    #[default]
    Model,
    Pipeline,
}

impl ForecastMissOrigin {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Model => "model",
            Self::Pipeline => "pipeline",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForecastOutcome {
    pub schema_version: String,
    pub outcome_id: String,
    pub idempotency_key: String,
    pub correlation_id: String,
    pub prediction_id: Option<String>,
    pub detector_id: String,
    pub detector_version: String,
    pub access_scope_digest: String,
    pub target_digest: String,
    pub metric: String,
    pub feature_cutoff: String,
    pub horizon_started_at: String,
    pub horizon_ended_at: String,
    pub direction: String,
    pub threshold: f64,
    pub predicted_value: Option<f64>,
    pub interval_lower: Option<f64>,
    pub interval_upper: Option<f64>,
    pub observed_value: Option<f64>,
    pub actual_breach_at: Option<String>,
    pub label: ForecastOutcomeLabel,
    pub miss_origin: Option<ForecastMissOrigin>,
    pub intervention_refs: Vec<String>,
    pub evidence_refs: Vec<String>,
    pub telemetry_completeness: TelemetryCompleteness,
    pub closed_at: String,
    pub mode: String,
    pub scoring_exclusions: Vec<ForecastScoringExclusion>,
}

impl ForecastOutcome {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.direction.as_str(), "rising" | "falling") { return Err("invalid direction literal"); }
        Ok(())
    }
}

pub const REJECTION_REF: &str = "^operational-evidence-rejection:sha256:[0-9a-f]{64}$";
impl ForecastOutcome {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn serialize_version(&self, mut handler: String) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_semantics(&self) -> Result<ForecastOutcome, &'static str> {
        if !(matches!(self.schema_version.as_str(), "1.0.0" | "1.1.0" | "1.2.0")) {
            return Err("forecast outcome schema version is unsupported");
        }
        if !(self.scoring_exclusions.clone()).is_empty() {
            if (self.schema_version.clone()) == (String::from("1.0.0")) {
                return Err("forecast scoring exclusions require schema version 1.1.0");
            }
        }
        if (self.actual_breach_at.is_some()) && (!(((self.feature_cutoff.clone()) <= ((self.actual_breach_at.clone()).unwrap_or_default())) && (((self.actual_breach_at.clone()).unwrap_or_default()) <= (self.closed_at.clone())))) {
            return Err("actual_breach_at MUST fall between feature cutoff and close time");
        }
        if (self.interval_lower.is_none()) != (self.interval_upper.is_none()) {
            return Err("forecast interval bounds MUST be supplied together");
        }
        Ok(self.clone())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ForecastOutcome", "ForecastOutcomeLabel", "ForecastMissOrigin", "TelemetryCompleteness", "ForecastScoringExclusion"];
