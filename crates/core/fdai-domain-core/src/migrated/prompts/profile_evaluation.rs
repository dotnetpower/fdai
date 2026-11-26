#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromptProfileComparison {
    pub capability_id: String,
    pub active_profile_id: String,
    pub active_profile_digest: String,
    pub treatment_profile_id: String,
    pub treatment_profile_digest: String,
    pub active_tokens: i64,
    pub treatment_tokens: i64,
}

impl PromptProfileComparison {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn token_reduction_rate(&self) -> f64 {
        0.0_f64
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn compare_prompt_profiles(mut registry: String, mut capability_id: String, mut treatment_profile_id: String) -> Result<PromptProfileComparison, &'static str> {
    Ok(PromptProfileComparison { capability_id: capability_id.clone(), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["PromptProfileComparison", "compare_prompt_profiles"];
