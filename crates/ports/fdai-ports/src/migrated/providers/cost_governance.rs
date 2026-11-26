#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostPackageActivation {
    pub vertical_id: String,
    pub package_id: String,
    pub available: bool,
    pub enabled: bool,
    pub availability_reasons: Vec<String>,
    pub package_version: String,
    pub image_digest: String,
    pub asset_manifest_digest: String,
    pub semantic_profile_digest: String,
    pub revision: i64,
    pub effective_at: String,
    pub ontology_release_id: String,
    pub ontology_release_digest: String,
    pub source_authority: String,
    pub previously_enabled: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostCollectionCursor {
    pub package_id: String,
    pub scope_id: String,
    pub revision: i64,
    pub resume_token: Option<String>,
    pub coverage_through_at: String,
    pub retention_floor_at: String,
    pub analysis_revision: i64,
    pub last_published_at: Option<String>,
    pub last_published_observation_id: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostObservation {
    pub observation_id: String,
    pub package_id: String,
    pub scope_id: String,
    pub service_id: String,
    pub amount: i64,
    pub currency: String,
    pub event_start_at: String,
    pub event_end_at: String,
    pub observed_at: String,
    pub recorded_at: String,
    pub source_authority: String,
    pub source_uri: String,
    pub completeness: i64,
    pub ontology_release_id: String,
    pub ontology_release_digest: String,
    pub evidence_digest: String,
    pub retention_until: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostObservationPage {
    pub observations: Vec<CostObservation>,
    pub next_resume_token: Option<String>,
    pub complete: bool,
    pub source_authority: String,
    pub bytes_read: i64,
    pub collected_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostCollectionRequest {
    pub package_id: String,
    pub scope_id: String,
    pub start_at: String,
    pub end_at: String,
    pub page_size: i64,
    pub deadline_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostAnalysisSample {
    pub scope_id: String,
    pub resource_id: String,
    pub amount_usd: i64,
    pub correlation_id: String,
    pub observed_at: String,
    pub source_authority: String,
    pub completeness: i64,
    pub ontology_release_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostAnomalyAdvisory {
    pub scope_id: String,
    pub resource_id: String,
    pub amount_usd: i64,
    pub baseline_usd: i64,
    pub ratio: i64,
    pub impact: i64,
    pub recommendation: String,
    pub correlation_id: String,
    pub observed_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SignedCostEffectEstimate {
    pub action_type: String,
    pub monthly_delta_usd: i64,
    pub confidence: i64,
    pub evidence_digest: String,
    pub source_authority: String,
    pub observed_at: String,
    pub valid_until: String,
}

pub const COST_SAMPLE_EVENT_TYPE: &str = "specialist.cost_sample";
pub const COST_OPTIMIZATION_EVENT_TYPE: &str = "specialist.cost_optimization_candidate";
pub const DIGEST_PREFIX: &str = "sha256:";
impl CostPackageActivation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn permits_activation_revision(&self, mut activation_revision: i64) -> bool {
        if (activation_revision) < (0_i64) {
            return false;
        }
        ((self.available) && ((self.enabled) && ((activation_revision) == (self.revision)))) || ((self.previously_enabled) && ((activation_revision) == ((self.revision).saturating_sub(1_i64))))
    }
}

pub trait CostPackageActivationReader {
    fn read_cost_activation(&self, package_id: String) -> String;
}

pub trait CostObservationProvider {
    fn collect_cost_page(&self, request: CostCollectionRequest, resume_token: Option<String>) -> String;
}

pub trait CostObservationStore {
    fn read_cost_cursor(&self, package_id: String, scope_id: String) -> String;
}

pub trait CostAdvisoryProvider {
    fn analyze_cost_sample(&self, sample: CostAnalysisSample) -> String;
}

pub trait CostSamplePublisher {
    fn publish_cost_sample(&self, observation: CostObservation, activation_revision: i64) -> String;
}

pub trait CostOptimizationCandidatePublisher {
    fn publish_cost_optimization_candidate(&self, candidate: std::collections::BTreeMap<String, String>, activation_revision: i64) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_text(mut name: String, mut value: String) -> Result<(), &'static str> {
    if ((value.clone()).trim().to_string()).is_empty() {
        return Err("name MUST be non-empty");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_aware(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["COST_SAMPLE_EVENT_TYPE", "COST_OPTIMIZATION_EVENT_TYPE", "CostAdvisoryProvider", "CostAnalysisSample", "CostAnomalyAdvisory", "CostCollectionCursor", "CostCollectionRequest", "CostObservation", "CostObservationPage", "CostObservationProvider", "CostObservationStore", "CostOptimizationCandidatePublisher", "CostPackageActivation", "CostPackageActivationReader", "CostSamplePublisher", "SignedCostEffectEstimate"];
