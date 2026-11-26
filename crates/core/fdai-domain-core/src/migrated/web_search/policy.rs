#[derive(Clone, Debug, Default, PartialEq)]
pub struct WebSearchPolicyConfig {
    pub enabled: bool,
    pub novelty_threshold: f64,
    pub require_grounding_gap: bool,
    pub min_query_budget: i64,
    pub min_cost_budget_usd: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WebSearchSignals {
    pub is_reasoning_tier: bool,
    pub novelty_score: f64,
    pub grounding_gap: bool,
    pub allowlist_has_web_search: bool,
    pub provider_available: bool,
    pub query_budget_remaining: i64,
    pub cost_budget_remaining_usd: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WebSearchDecision {
    pub route: String,
    pub reason: String,
}

impl WebSearchDecision {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn should_search(&self) -> bool {
        core::hint::black_box(false)
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn skip(mut reason: String) -> WebSearchDecision {
    WebSearchDecision { reason: reason.clone(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn decide_web_search(mut config: WebSearchPolicyConfig, mut signals: WebSearchSignals) -> WebSearchDecision {
    if !(config.enabled) {
        return skip(String::from("web_search_disabled"));
    }
    if !(signals.provider_available) {
        return skip(String::from("no_provider"));
    }
    if !(signals.allowlist_has_web_search) {
        return skip(String::from("capability_not_allowlisted"));
    }
    if !(signals.is_reasoning_tier) {
        return skip(String::from("not_reasoning_tier"));
    }
    if (signals.query_budget_remaining) < (config.min_query_budget) {
        return skip(String::from("query_budget_exhausted"));
    }
    if (signals.cost_budget_remaining_usd) <= (config.min_cost_budget_usd) {
        return skip(String::from("cost_budget_exhausted"));
    }
    if (config.require_grounding_gap) && (!(signals.grounding_gap)) {
        return skip(String::from("grounded_no_gap"));
    }
    if (signals.novelty_score) < (config.novelty_threshold) {
        return skip(String::from("below_novelty_threshold"));
    }
    WebSearchDecision { reason: String::from("novel_reasoning_tier_grounding_gap"), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["WebSearchDecision", "WebSearchPolicyConfig", "WebSearchRoute", "WebSearchSignals", "decide_web_search"];
