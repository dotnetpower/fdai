pub const HOUR: i64 = 3600;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationIntentSpec {
    pub intent: String,
    pub plan_id: String,
    pub default_tools: Vec<String>,
    pub interactive_tools: Vec<String>,
    pub lookback_seconds: i64,
}

impl ReadInvestigationIntentSpec {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.intent.trim().is_empty() { return Err("intent must be non-empty"); }
        if self.plan_id.trim().is_empty() { return Err("plan_id must be non-empty"); }
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn read_investigation_intent_spec(mut intent: String) -> ReadInvestigationIntentSpec {
    if intent.is_empty() {
        return Default::default();
    }
    Default::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["READ_INVESTIGATION_INTENT_SPECS", "ReadInvestigationIntentSpec", "read_investigation_intent_spec"];
