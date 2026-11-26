#[derive(Clone, Debug, Default, PartialEq)]
pub struct PipelineRun {
    pub candidate_report: String,
    pub decision: String,
    pub promotion: String,
    pub baseline: Option<String>,
    pub baseline_report: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ContinuousRulePipeline {
    pub regression_gate: String,
    pub promotion: String,
    pub evaluator: Option<String>,
}

impl ContinuousRulePipeline {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn run(&self, mut candidate_rules: Vec<String>, mut scenario_set_id: String, mut scenarios: Option<Vec<std::collections::BTreeMap<String, String>>>, mut scenarios_dir: Option<String>, mut baseline_rules: Option<Vec<String>>, mut previous_baseline: Option<String>) -> PipelineRun {
        let candidate_rules_tuple: Vec<String> = candidate_rules.clone();
        let candidate_report: String = self.replay(candidate_rules_tuple.clone(), scenario_set_id.clone(), scenarios.clone(), scenarios_dir.clone()).unwrap_or_else(|_| String::new());
        let mut baseline_report: Option<String> = None;
        if let Some(mut baseline_rules) = baseline_rules.clone() {
            baseline_report = Some(self.replay(baseline_rules.clone(), format!("{}::baseline", scenario_set_id.clone()), scenarios.clone(), scenarios_dir.clone()).unwrap_or_else(|_| String::new()));
        }
        PipelineRun { candidate_report: candidate_report.clone(), baseline_report: baseline_report.clone(), ..Default::default() }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn replay(&self, mut rules: Vec<String>, mut scenario_set_id: String, mut scenarios: Option<Vec<std::collections::BTreeMap<String, String>>>, mut scenarios_dir: Option<String>) -> Result<String, &'static str> {
        if (scenarios.is_none()) == (scenarios_dir.is_none()) {
            return Err("provide exactly one of scenarios or scenarios_dir");
        }
        let Some(mut scenarios) = scenarios.clone() else { return Err("scenarios were None after narrowing"); };
        Ok(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_pipeline(mut audit_store: String, mut evaluator: Option<String>, mut regression_gate: Option<String>) -> ContinuousRulePipeline {
    ContinuousRulePipeline { evaluator: evaluator.clone(), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ContinuousRulePipeline", "PipelineRun", "build_pipeline"];
