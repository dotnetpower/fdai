#[derive(Clone, Debug, Default, PartialEq)]
pub struct ToolGatherResult {
    pub plans: Vec<String>,
    pub results: Vec<String>,
    pub timed_out: bool,
    pub ambiguous: bool,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn plan_tools(mut question: String, mut semantic: Option<String>, mut agents: Vec<String>, mut limit: i64) -> Vec<String> {
    if question.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn prefetch_tools(mut question: String, mut registry: String, mut semantic: Option<String>, mut agents: Vec<String>, mut limit: i64, mut trace_ref: String) -> Vec<String> {
    if question.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::too_many_arguments)]
pub async fn gather_tools(mut question: String, mut registry: String, mut semantic: Option<String>, mut agents: Vec<String>, mut limit: i64, mut trace_ref: String, mut execute_limit: Option<i64>, mut require_unique_top: bool) -> ToolGatherResult {
    let mut results: Vec<String> = Vec::<String>::new();
    let mut plans: Vec<String> = plan_tools(question.clone(), semantic.clone(), agents.clone(), limit).await;
    let mut ordered_results: Vec<String> = Vec::<String>::new();
    results.extend(ordered_results.clone());
    ToolGatherResult { plans: plans.clone(), results: results.clone(), timed_out: false, ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PREFETCH_BUDGET_SECONDS", "ToolGatherResult", "gather_tools", "plan_tools", "prefetch_tools"];
