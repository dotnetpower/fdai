#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromotionStageCriteria {
    pub source_channel: String,
    pub target_channel: String,
    pub required_labels: Vec<String>,
    pub min_soak_seconds: i64,
    pub min_healthy_canaries: i64,
    pub max_stage_timeout_seconds: i64,
}

impl PromotionStageCriteria {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.source_channel.trim().is_empty() { return Err("source_channel must be non-empty"); }
        if self.target_channel.trim().is_empty() { return Err("target_channel must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CanaryObservation {
    pub installation_id: String,
    pub release_id: String,
    pub healthy: bool,
    pub soak_seconds: i64,
}

impl CanaryObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.installation_id.trim().is_empty() { return Err("installation_id must be non-empty"); }
        if self.release_id.trim().is_empty() { return Err("release_id must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromotionStageInput {
    pub release_id: String,
    pub present_in_source_channel: bool,
    pub labels: Vec<String>,
    pub canary_observations: Vec<CanaryObservation>,
    pub elapsed_stage_seconds: i64,
    pub capability_ids: Vec<String>,
    pub recall_records: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BoundaryRegistryMirror {
    pub mirrored_digests: Vec<String>,
}

pub const IMAGE_DIGEST: &str = "sha256:[0-9a-f]{64}\\Z";
impl BoundaryRegistryMirror {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn missing_for(&self, mut release: String) -> std::collections::BTreeSet<String> {
        std::collections::BTreeSet::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn mirror_release(&self, mut release: String, mut available_upstream_digests: Vec<String>) -> Result<BoundaryRegistryMirror, &'static str> {
        let upstream: std::collections::BTreeSet<String> = (available_upstream_digests.clone()).into_iter().collect::<std::collections::BTreeSet<String>>();
        Ok(BoundaryRegistryMirror::default())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn evaluate_promotion_stage(mut criteria: PromotionStageCriteria, mut stage_input: PromotionStageInput) -> String {
    core::hint::black_box(String::new())
}

