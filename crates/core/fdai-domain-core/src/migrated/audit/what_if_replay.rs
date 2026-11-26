use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReconstructedEvent {
    pub correlation_id: String,
    pub resource_id: String,
    pub resource_type: String,
    pub props: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WhatIfReplayReport {
    pub event: Box<ReconstructedEvent>,
    #[allow(clippy::type_complexity)]
    pub matched_rules: Vec<BTreeMap<String, String>>,
    pub original_action_kinds: Vec<String>,
}

impl ReconstructedEvent {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn as_json(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("correlation_id"), self.correlation_id.clone()), (String::from("resource_id"), self.resource_id.clone()), (String::from("resource_type"), self.resource_type.clone()), (String::from("props"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EventReconstructionError {
    pub message: String,
}

impl EventReconstructionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for EventReconstructionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for EventReconstructionError {}

pub trait WhatIfEvaluator {
    #[allow(clippy::type_complexity)]
    fn evaluate(&self, resource_type: String, resource_props: std::collections::BTreeMap<String, String>) -> Vec<std::collections::BTreeMap<String, String>>;
}

impl WhatIfReplayReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn as_json(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("event"), String::new()), (String::from("matched_rules"), String::new()), (String::from("original_action_kinds"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn reconstruct_event(mut correlation_id: String, mut items: Vec<String>) -> Result<ReconstructedEvent, &'static str> {
    if (correlation_id.trim().to_string()).is_empty() {
        return Err("correlation_id MUST be non-empty");
    }
    if (items.clone()).is_empty() {
        return Err("no audit items for correlation_id correlation_idr");
    }
    Ok(ReconstructedEvent { correlation_id: correlation_id.trim().to_string(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn replay_with_what_if(mut correlation_id: String, mut items: Vec<String>, mut evaluator: String) -> WhatIfReplayReport {
    let event: ReconstructedEvent = reconstruct_event(correlation_id.clone(), items.clone()).unwrap_or_else(|_| Default::default());
    WhatIfReplayReport { event: Box::new(event.clone()), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["EventReconstructionError", "ReconstructedEvent", "WhatIfEvaluator", "WhatIfReplayReport", "reconstruct_event", "replay_with_what_if"];
