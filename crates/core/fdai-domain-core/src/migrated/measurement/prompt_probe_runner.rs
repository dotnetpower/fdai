use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecognitionSample {
    pub composed_prompt: String,
    #[allow(clippy::type_complexity)]
    pub response_json: Option<BTreeMap<String, String>>,
    pub response_text: String,
    pub expected: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecognitionRunReport {
    pub samples: Vec<String>,
    pub summary: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecognitionScenario {
    pub id: String,
    pub capability_id: String,
    pub scope: Option<String>,
    pub expected: String,
}

pub trait ScenarioResponder {
    #[allow(clippy::type_complexity)]
    fn respond(&self, composed_prompt: String, capability_id: String) -> (Option<std::collections::BTreeMap<String, String>>, String);
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn score_batch(mut samples: Vec<RecognitionSample>) -> RecognitionRunReport {
    RecognitionRunReport::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn score_sample(mut sample: RecognitionSample) -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn run_scenarios(mut composer: String, mut responder: String, mut scenarios: Vec<RecognitionScenario>) -> RecognitionRunReport {
    let mut samples: Vec<RecognitionSample> = Vec::<RecognitionSample>::new();
    for scenario in scenarios.clone() {
        samples.push(RecognitionSample { expected: scenario.expected.clone(), ..Default::default() });
    }
    score_batch(samples.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["RecognitionRunReport", "RecognitionSample", "RecognitionScenario", "ScenarioResponder", "run_scenarios", "score_batch"];
