use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct EscalationIssue {
    pub key: String,
    pub message: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LadderSelector {
    pub environment: String,
    pub finding_class: String,
    pub impact_at_least: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EscalationRung {
    pub rung: String,
    pub audience_group: String,
    pub ttl_seconds: i64,
    pub category: String,
    pub also_page: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EscalationLadder {
    pub id: String,
    pub priority: i64,
    pub select_when: Box<LadderSelector>,
    pub rungs: Vec<EscalationRung>,
    pub overall_deadline_seconds: i64,
    pub description: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct UrgencyPolicy {
    pub id: String,
    pub lead_time_factor: f64,
    pub min_forecast_confidence: f64,
    pub min_effective_ttl_seconds: i64,
    pub description: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EscalationCatalog {
    pub ladders: Vec<EscalationLadder>,
    pub urgency_policies: Vec<UrgencyPolicy>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RungWindow {
    pub rung: Box<EscalationRung>,
    pub effective_ttl_seconds: i64,
    pub starts_at_seconds: i64,
    pub expires_at_seconds: i64,
    pub compressed: bool,
    pub metadata: BTreeMap<String, String>,
}

pub const LADDER_KIND: &str = "escalation_ladder";
pub const URGENCY_KIND: &str = "urgency_policy";
pub const IMPACT_ORDER: &[&str] = &["resource", "resource_group", "subscription"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EscalationCatalogError {
    pub message: String,
}

impl EscalationCatalogError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for EscalationCatalogError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for EscalationCatalogError {}

impl EscalationLadder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn declared_walk_seconds(&self) -> i64 {
        0_i64
    }
}

impl EscalationCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn urgency_policy(&self, mut policy_id: String) -> Option<UrgencyPolicy> {
        for policy in self.urgency_policies.clone() {
            if (policy.id.clone()) == (policy_id.clone()) {
                return Some(policy.clone());
            }
        }
        None
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_schema(mut path: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn ladder_invariants(mut raw: std::collections::BTreeMap<String, String>, mut key: String) -> Vec<EscalationIssue> {
    let mut issues: Vec<EscalationIssue> = Vec::<EscalationIssue>::new();
    let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    issues.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn to_ladder(mut raw: std::collections::BTreeMap<String, String>) -> EscalationLadder {
    EscalationLadder { select_when: Box::new(LadderSelector::default()), description: ((raw.clone()).get("description").cloned().unwrap_or_else(|| String::from(""))).trim().to_string(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn to_urgency_policy(mut raw: std::collections::BTreeMap<String, String>) -> UrgencyPolicy {
    UrgencyPolicy { description: ((raw.clone()).get("description").cloned().unwrap_or_else(|| String::from(""))).trim().to_string(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_escalation_catalog(mut root: String) -> Result<EscalationCatalog, &'static str> {
    let mut issues: Vec<EscalationIssue> = Vec::<EscalationIssue>::new();
    let mut ladders: Vec<EscalationLadder> = Vec::<EscalationLadder>::new();
    let mut policies: Vec<UrgencyPolicy> = Vec::<UrgencyPolicy>::new();
    let mut ladder_ids: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let mut priorities: std::collections::BTreeMap<i64, String> = std::collections::BTreeMap::<i64, String>::new();
    let mut policy_ids: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    if !(issues.clone()).is_empty() {
        return Err("issues");
    }
    Ok(EscalationCatalog::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn impact_rank(mut impact: String) -> Result<i64, &'static str> {
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn select_ladder(mut catalog: EscalationCatalog, mut environment: String, mut finding_class: String, mut impact: String) -> Option<EscalationLadder> {
    let rank: i64 = impact_rank(impact.clone()).unwrap_or_else(|_| 0_i64);
    for ladder in catalog.ladders.clone() {
        let selector: LadderSelector = *(ladder.select_when.clone());
        if ((selector.environment.clone()) == (environment.clone())) && (((selector.finding_class.clone()) == (finding_class.clone())) && ((rank) >= (impact_rank(selector.impact_at_least.clone()).unwrap_or_else(|_| 0_i64)))) {
            return Some(ladder.clone());
        }
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn resolve_schedule(mut ladder: EscalationLadder, mut policy: Option<UrgencyPolicy>, mut remaining_lead_time_seconds: Option<i64>, mut forecast_confidence: Option<f64>) -> Result<Vec<RungWindow>, &'static str> {
    let mut compressed_ttl: Option<i64> = None;
    let mut windows: Vec<RungWindow> = Vec::<RungWindow>::new();
    let mut cursor: i64 = 0_i64;
    for rung in ladder.rungs.clone() {
        let mut effective: i64 = rung.ttl_seconds;
        if let Some(mut compressed_ttl) = compressed_ttl.clone() {
            effective = (rung.ttl_seconds).min(compressed_ttl);
        }
        windows.push(RungWindow { rung: Box::new(rung.clone()), effective_ttl_seconds: effective, starts_at_seconds: cursor, expires_at_seconds: (cursor).saturating_add(effective), ..Default::default() });
        cursor = cursor.saturating_add(effective);
    }
    Ok(windows.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn rung_at_elapsed(mut schedule: Vec<RungWindow>, mut elapsed_seconds: i64) -> Result<Option<RungWindow>, &'static str> {
    if (elapsed_seconds) < (0_i64) {
        return Err("elapsed_seconds MUST be  0");
    }
    for window in schedule.clone() {
        if (elapsed_seconds) < (window.expires_at_seconds) {
            return Ok(Some(window.clone()));
        }
    }
    Ok(None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn fallback_channels(mut schedule: Vec<RungWindow>) -> Vec<String> {
    let mut ordered: Vec<String> = Vec::<String>::new();
    ordered.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["EscalationCatalog", "EscalationCatalogError", "EscalationIssue", "EscalationLadder", "EscalationRung", "LadderSelector", "RungWindow", "UrgencyPolicy", "fallback_channels", "load_escalation_catalog", "resolve_schedule", "rung_at_elapsed", "select_ladder"];
