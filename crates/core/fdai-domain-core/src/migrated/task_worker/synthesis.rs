pub const MAX_WORKERS: i64 = 8;
pub const MAX_SUMMARY_CHARS: i64 = 4000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TaskWorkerContribution {
    pub worker_id: String,
    pub status: String,
    pub summary: Option<String>,
    pub evidence_refs: Vec<String>,
    pub caveats: Vec<String>,
    pub usage: String,
    pub terminal_reason: String,
    pub trusted: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TaskWorkerSynthesis {
    pub answer_planning: String,
    pub workers: Vec<TaskWorkerContribution>,
    pub total_usage: String,
    pub unique_evidence_refs: Vec<String>,
}

impl TaskWorkerSynthesis {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("mode"), String::from("shadow")), (String::from("trusted"), String::new()), (String::from("answer_planning"), String::new()), (String::from("workers"), String::new()), (String::from("total_usage"), String::new()), (String::from("unique_evidence_refs"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn synthesize_task_worker_results(mut answer_planning: String, mut results: Vec<String>) -> Result<TaskWorkerSynthesis, &'static str> {
    if (((results.clone()).len() as i64)) > (MAX_WORKERS) {
        return Err("task worker synthesis accepts at most _MAX_WORKERS results");
    }
    Ok(TaskWorkerSynthesis { answer_planning: answer_planning.clone(), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["TaskWorkerContribution", "TaskWorkerSynthesis", "synthesize_task_worker_results"];
