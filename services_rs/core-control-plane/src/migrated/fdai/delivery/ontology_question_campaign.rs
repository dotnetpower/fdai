use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct QuestionCampaignWork {
    pub identity: String,
    pub universe: String,
    pub cases: Vec<String>,
    pub generation_inputs: BTreeMap<String, String>,
    pub prior_questions: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyQuestionCampaignJobResult {
    pub state: String,
    pub reason: String,
    pub campaign: Option<String>,
    pub execution_authority: bool,
}

pub trait QuestionCampaignWorkProvider {
    fn build(&self, question_budget: i64, scheduled: bool) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OntologyQuestionCampaignJob {
    pub initialized: bool,
}

impl OntologyQuestionCampaignJob {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run_manual(&self, mut question_budget: i64) -> Result<OntologyQuestionCampaignJobResult, &'static str> {
        if !(((1_i64) <= (question_budget)) && ((question_budget) <= (100_i64))) {
            return Err("manual question campaign budget MUST be in 1 100");
        }
        Ok(self.run_campaign(question_budget, false).await.unwrap_or_else(|_| Default::default()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run_scheduled(&self, mut profile: String, mut prerequisites: String, mut now: String, mut last_started_at: Option<String>) -> OntologyQuestionCampaignJobResult {
        self.run_campaign(0_i64, true).await.unwrap_or_else(|_| Default::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run_campaign(&self, mut question_budget: i64, mut scheduled: bool) -> Result<OntologyQuestionCampaignJobResult, &'static str> {
        Ok(OntologyQuestionCampaignJobResult::default())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn project_job_result(mut result: OntologyQuestionCampaignJobResult) -> std::collections::BTreeMap<String, String> {
    let campaign: Option<String> = result.campaign.clone();
    std::collections::BTreeMap::from([(String::from("state"), result.state.clone()), (String::from("reason"), result.reason.clone()), (String::from("campaign_id"), String::new()), (String::from("selected_case_count"), String::new()), (String::from("terminal_case_count"), String::new()), (String::from("hard_zero_total"), String::new()), (String::from("release_evidence_eligible"), String::new()), (String::from("execution_authority"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["OntologyQuestionCampaignJob", "OntologyQuestionCampaignJobResult", "QuestionCampaignWork", "QuestionCampaignWorkProvider", "project_job_result"];
