#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ActionOutcomeDisposition {
    #[default]
    Resolved,
    WaitingForOutcome,
    WaitingForVerifier,
}

impl ActionOutcomeDisposition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Resolved => "resolved",
            Self::WaitingForOutcome => "waiting_for_action_outcome",
            Self::WaitingForVerifier => "waiting_for_action_outcome_verifier",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionOutcomeResolution {
    pub disposition: ActionOutcomeDisposition,
    pub outcome: Option<String>,
    pub safeguard_bundle_digest: Option<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn reported_bundle_digest(mut context: std::collections::BTreeMap<String, String>, mut step_id: String) -> Option<String> {
    (Some(((context.clone()).get((format!("action.{}.safeguard_bundle_digest", step_id.clone())).as_str()).cloned().unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn resolve_action_outcome(mut verifier: String, mut process_id: String, mut step_id: String, mut proposal_ref: String, mut context: std::collections::BTreeMap<String, String>) -> ActionOutcomeResolution {
    let status: Option<String> = (context.clone()).get((format!("action.{}.status", step_id.clone())).as_str()).cloned();
    let mut receipt_ref: String = ((context.clone()).get((format!("action.{}.receipt_ref", step_id.clone())).as_str()).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    let mut bundle_digest: Option<String> = reported_bundle_digest(context.clone(), step_id.clone());
    let mut outcome: String = if (status.clone()) == Some(String::from("verified")) { String::from("succeeded") } else { String::from("failed") };
    ActionOutcomeResolution { outcome: Some(outcome.clone()), safeguard_bundle_digest: bundle_digest.clone(), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ActionOutcomeDisposition", "ActionOutcomeResolution", "reported_bundle_digest", "resolve_action_outcome"];
