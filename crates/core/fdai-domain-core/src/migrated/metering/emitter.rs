pub const UNCORRELATED: &str = "uncorrelated";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MeteringEmitter {
    pub initialized: bool,
}

impl MeteringEmitter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn emit_safe(&mut self, mut usage: String, mut correlation_id: Option<String>, mut usage_scope: Option<String>, mut cached_prompt_tokens: i64, mut duration_ms: i64, mut profile_digest: Option<String>, mut locale: String, mut turn_family: String, mut disposition: String) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn utc_now() -> String {
    core::hint::black_box(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["MeteringEmitter"];
