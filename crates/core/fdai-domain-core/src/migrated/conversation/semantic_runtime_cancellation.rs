pub const MODEL_THREAD_CANCELLATION_GRACE_SECONDS: f64 = 1.0;
pub const PENDING_MODEL_THREAD_DRAINS: &[&str] = &[];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn run_preflight_with_cancellation(mut planner: String, mut utterance: String, mut prior_turns: Vec<String>, mut locale: String, mut conversation_profile: Option<std::collections::BTreeMap<String, String>>, mut cancelled: Option<String>, mut conversation_model_tier: Option<String>) -> Result<String, &'static str> {
    if planner.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn run_planning_with_cancellation(mut operation: String, mut cancelled: Option<String>) -> Result<String, &'static str> {
    let mut worker: Option<String> = None;
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["_run_planning_with_cancellation", "_run_preflight_with_cancellation"];
