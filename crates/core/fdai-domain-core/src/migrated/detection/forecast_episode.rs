use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ForecastEvaluationKind {
    #[default]
    PredictedBreach,
    PredictedNoBreach,
    Abstained,
}

impl ForecastEvaluationKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::PredictedBreach => "predicted_breach",
            Self::PredictedNoBreach => "predicted_no_breach",
            Self::Abstained => "abstained",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ForecastEpisodeState {
    #[default]
    Open,
    Closed,
}

impl ForecastEpisodeState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::Closed => "closed",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ForecastClosureReason {
    #[default]
    Scored,
    NegativeNoBreach,
    AbstainedNoBreach,
}

impl ForecastClosureReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Scored => "scored",
            Self::NegativeNoBreach => "negative_no_breach",
            Self::AbstainedNoBreach => "abstained_no_breach",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForecastEpisodeClosure {
    pub episode_id: String,
    pub expected_revision: i64,
    pub closed_at: String,
    pub reason: ForecastClosureReason,
    #[allow(clippy::type_complexity)]
    pub outcome_payload: Option<BTreeMap<String, String>>,
    pub observation: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForecastPublicationOutboxItem {
    pub publication_id: String,
    pub episode_id: String,
    pub topic: String,
    pub payload: BTreeMap<String, String>,
    pub attempts: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForecastEpisode {
    pub episode_id: String,
    pub correlation_id: String,
    pub detector_id: String,
    pub detector_version: String,
    pub scorer_version: String,
    pub access_scope_digest: String,
    pub target_ref: String,
    pub metric: String,
    pub feature_cutoff: String,
    pub horizon_started_at: String,
    pub horizon_ended_at: String,
    pub telemetry_grace_seconds: i64,
    pub direction: String,
    pub threshold: f64,
    pub evaluation_kind: ForecastEvaluationKind,
    pub evidence_refs: Vec<String>,
    pub predicted_value: Option<f64>,
    pub interval_lower: Option<f64>,
    pub interval_upper: Option<f64>,
    pub abstain_reason: Option<String>,
    pub mode: String,
    pub state: ForecastEpisodeState,
    pub revision: i64,
}

impl ForecastEpisode {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.episode_id.trim().is_empty() { return Err("episode_id must be non-empty"); }
        if self.correlation_id.trim().is_empty() { return Err("correlation_id must be non-empty"); }
        if self.detector_id.trim().is_empty() { return Err("detector_id must be non-empty"); }
        if self.detector_version.trim().is_empty() { return Err("detector_version must be non-empty"); }
        if self.scorer_version.trim().is_empty() { return Err("scorer_version must be non-empty"); }
        if self.access_scope_digest.trim().is_empty() { return Err("access_scope_digest must be non-empty"); }
        if self.target_ref.trim().is_empty() { return Err("target_ref must be non-empty"); }
        if self.metric.trim().is_empty() { return Err("metric must be non-empty"); }
        if self.feature_cutoff.trim().is_empty() { return Err("feature_cutoff must be non-empty"); }
        if self.horizon_started_at.trim().is_empty() { return Err("horizon_started_at must be non-empty"); }
        if self.horizon_ended_at.trim().is_empty() { return Err("horizon_ended_at must be non-empty"); }
        if self.direction.trim().is_empty() { return Err("direction must be non-empty"); }
        if self.mode.trim().is_empty() { return Err("mode must be non-empty"); }
        Ok(())
    }
}

pub trait ForecastEpisodeStore {
    #[allow(clippy::type_complexity)]
    fn record(&self, episode: ForecastEpisode, forecast_payload: Option<std::collections::BTreeMap<String, String>>) -> String;
}

impl ForecastEpisode {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn closure_due_at(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn target_digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn forecast_episode_id(mut access_scope_digest: String, mut detector_id: String, mut detector_version: String, mut target_ref: String, mut metric: String, mut feature_cutoff: String, mut horizon_ended_at: String) -> String {
    if access_scope_digest.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn forecast_publication_id(mut episode_id: String, mut topic: String) -> String {
    if episode_id.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ForecastClosureReason", "ForecastEpisode", "ForecastEpisodeClosure", "ForecastEpisodeState", "ForecastEpisodeStore", "ForecastEvaluationKind", "ForecastPublicationOutboxItem", "forecast_publication_id", "forecast_episode_id"];
