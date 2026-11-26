use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct DebateRouterConfig {
    pub enabled: bool,
    pub on_cross_check_disagreement: bool,
    pub always_for_action_types: Vec<String>,
    pub never_for_action_types: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DebateRoutingDecision {
    pub route: String,
    pub reason: String,
    pub action_type: String,
    pub metadata: BTreeMap<String, String>,
}

pub const REASON_DISABLED: &str = "disabled";
pub const REASON_ORCH_UNAVAILABLE: &str = "orchestrator_unavailable";
pub const REASON_NEVER_LIST: &str = "never_list";
pub const REASON_ALWAYS_LIST: &str = "always_list";
pub const REASON_DISAGREEMENT: &str = "cross_check_disagreement";
pub const REASON_DEFAULT_SKIP: &str = "default_skip";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn decide_debate_route(mut candidate: String, mut cross_check_disagreed: bool, mut orchestrator_available: bool, mut config: Option<DebateRouterConfig>) -> DebateRoutingDecision {
    if !(orchestrator_available) {
        return DebateRoutingDecision { reason: String::from(REASON_ORCH_UNAVAILABLE), ..Default::default() };
    }
    DebateRoutingDecision { reason: String::from(REASON_DEFAULT_SKIP), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["DebateRoute", "DebateRouterConfig", "DebateRoutingDecision", "decide_debate_route"];
