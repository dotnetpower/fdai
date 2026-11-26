#[derive(Clone, Debug, Default, PartialEq)]
pub struct QuestionScheduleProfile {
    pub profile_id: String,
    pub cron: String,
    pub generation_profile: String,
    pub model_profile: String,
    pub question_budget: i64,
    pub time_budget_seconds: i64,
    pub no_progress_seconds: i64,
    pub token_budget: i64,
    pub cost_budget_microusd: i64,
    pub locales: Vec<String>,
    pub perspectives: Vec<String>,
    pub enabled: bool,
    pub timezone: String,
    pub mode: String,
}

impl QuestionScheduleProfile {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.profile_id.trim().is_empty() { return Err("profile_id must be non-empty"); }
        if self.cron.trim().is_empty() { return Err("cron must be non-empty"); }
        if self.generation_profile.trim().is_empty() { return Err("generation_profile must be non-empty"); }
        if self.model_profile.trim().is_empty() { return Err("model_profile must be non-empty"); }
        if self.timezone.trim().is_empty() { return Err("timezone must be non-empty"); }
        if self.mode.trim().is_empty() { return Err("mode must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct QuestionWorkloadPrincipalReceipt {
    pub principal_digest: String,
    pub role: String,
    pub role_source: String,
    pub scope_digest: String,
    pub purpose: String,
    pub authentication_evidence_digest: String,
    pub authenticated_at: String,
    pub expires_at: String,
    pub principal_kind: String,
}

impl QuestionWorkloadPrincipalReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.principal_digest.trim().is_empty() { return Err("principal_digest must be non-empty"); }
        if self.role.trim().is_empty() { return Err("role must be non-empty"); }
        if self.role_source.trim().is_empty() { return Err("role_source must be non-empty"); }
        if self.scope_digest.trim().is_empty() { return Err("scope_digest must be non-empty"); }
        if self.purpose.trim().is_empty() { return Err("purpose must be non-empty"); }
        if self.authentication_evidence_digest.trim().is_empty() { return Err("authentication_evidence_digest must be non-empty"); }
        if self.authenticated_at.trim().is_empty() { return Err("authenticated_at must be non-empty"); }
        if self.expires_at.trim().is_empty() { return Err("expires_at must be non-empty"); }
        if self.principal_kind.trim().is_empty() { return Err("principal_kind must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct QuestionCampaignPrerequisites {
    pub previous_campaign_terminal: bool,
    pub ontology_available: bool,
    pub manifest_available: bool,
    pub semantic_transport_ready: bool,
    #[allow(clippy::type_complexity)]
    pub workload_principal: Option<Box<QuestionWorkloadPrincipalReceipt>>,
    pub generation_model_available: bool,
    pub evidence_minimum_ready: bool,
    pub budget_remaining: bool,
    pub campaign_lock_available: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct QuestionCampaignDueDecision {
    pub state: String,
    pub reason: String,
    pub due: bool,
    pub execution_authority: bool,
}

pub const PROFILE_ID_PATTERN: &str = "[a-z][a-z0-9.-]{0,95}";
pub const DIGEST_PATTERN: &str = "sha256:[0-9a-f]{64}";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn evaluate_question_campaign_due(mut profile: QuestionScheduleProfile, mut prerequisites: QuestionCampaignPrerequisites, mut now: String, mut last_started_at: Option<String>) -> Result<QuestionCampaignDueDecision, &'static str> {
    if !(profile.enabled) {
        return Ok(decision(String::from("skipped"), String::from("schedule_disabled")));
    }
    let principal: Option<QuestionWorkloadPrincipalReceipt> = prerequisites.workload_principal.clone().map(|_b| *_b);
    Ok(decision(String::from("due"), String::from("campaign_due")))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn decision(mut state: String, mut reason: String) -> QuestionCampaignDueDecision {
    QuestionCampaignDueDecision { state: state.clone(), reason: reason.clone(), due: (state.clone()) == (String::from("due")), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["QuestionCampaignDueDecision", "QuestionCampaignPrerequisites", "QuestionScheduleProfile", "QuestionWorkloadPrincipalReceipt", "evaluate_question_campaign_due"];
