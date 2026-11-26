#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnalysisEvaluationMetrics {
    pub true_positive: i64,
    pub false_positive: i64,
    pub false_negative: i64,
    pub true_negative: i64,
    pub unsupported: i64,
    pub precision: f64,
    pub recall: f64,
    pub f1: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnalysisEvaluationReceipt {
    pub schema_version: String,
    pub corpus_id: String,
    pub corpus_version: String,
    pub corpus_digest: String,
    pub language: String,
    pub rule_id: String,
    pub rule_version: String,
    pub dev: Box<AnalysisEvaluationMetrics>,
    pub holdout: Box<AnalysisEvaluationMetrics>,
    pub cases: Vec<AnalysisCaseObservation>,
    pub corpus_size: i64,
    pub graph_nodes: i64,
    pub graph_edges: i64,
    pub analyzed_function_share: f64,
    pub multi_file_path_recall: f64,
    pub framework_coverage: f64,
    pub fix_regression_rate: f64,
    pub meets_initial_thresholds: bool,
    pub promotion_eligible: bool,
    pub duration_ms: i64,
    pub peak_memory_kib: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnalysisCaseObservation {
    pub case_id: String,
    pub split: String,
    pub vulnerable: bool,
    pub detected: bool,
    pub supported: bool,
    pub graph_nodes: i64,
    pub graph_edges: i64,
    pub functions: i64,
    pub files: i64,
    pub path_count: i64,
    pub multi_file_paths: i64,
    pub framework_sources: i64,
    pub duration_ms: i64,
    pub peak_memory_kib: i64,
}

pub const REVISION: &str = "0000000000000000000000000000000000000000";
impl AnalysisEvaluationReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn stable_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn analysis_evaluation_metrics(mut outcomes: Vec<(bool, bool, bool)>) -> AnalysisEvaluationMetrics {
    AnalysisEvaluationMetrics::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn evaluate_analysis(mut corpus: String, mut rule: String, mut work_root: String, mut analyzer: String) -> Result<AnalysisEvaluationReceipt, &'static str> {
    let outcomes: std::collections::BTreeMap<String, Vec<(bool, bool, bool)>> = std::collections::BTreeMap::from([(String::from("dev"), Vec::<(bool, bool, bool)>::new()), (String::from("holdout"), Vec::<(bool, bool, bool)>::new())]);
    let mut observations: Vec<AnalysisCaseObservation> = Vec::<AnalysisCaseObservation>::new();
    let dev: AnalysisEvaluationMetrics = analysis_evaluation_metrics(Vec::new());
    let holdout: AnalysisEvaluationMetrics = analysis_evaluation_metrics(Vec::new());
    Ok(AnalysisEvaluationReceipt { schema_version: String::from("1.0.0"), dev: Box::new(dev.clone()), holdout: Box::new(holdout.clone()), cases: observations.clone(), corpus_size: ((observations.clone()).len() as i64), promotion_eligible: false, ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn evaluate_python_analysis(mut corpus: String, mut rule: String, mut work_root: String) -> Result<AnalysisEvaluationReceipt, &'static str> {
    Ok(evaluate_analysis(corpus.clone(), rule.clone(), work_root.clone(), String::new()).unwrap_or_else(|_| Default::default()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn evaluate_java_analysis(mut corpus: String, mut rule: String, mut work_root: String, mut compiler: Option<String>) -> Result<AnalysisEvaluationReceipt, &'static str> {
    Ok(evaluate_analysis(corpus.clone(), rule.clone(), work_root.clone(), String::new()).unwrap_or_else(|_| Default::default()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn evaluate_typescript_analysis(mut corpus: String, mut rule: String, mut work_root: String, mut config: String) -> Result<AnalysisEvaluationReceipt, &'static str> {
    Ok(evaluate_analysis(corpus.clone(), rule.clone(), work_root.clone(), String::new()).unwrap_or_else(|_| Default::default()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn evaluate_csharp_analysis(mut corpus: String, mut rule: String, mut work_root: String, mut config: String) -> Result<AnalysisEvaluationReceipt, &'static str> {
    Ok(evaluate_analysis(corpus.clone(), rule.clone(), work_root.clone(), String::new()).unwrap_or_else(|_| Default::default()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["AnalysisEvaluationMetrics", "AnalysisEvaluationReceipt", "AnalysisCaseObservation", "analysis_evaluation_metrics", "evaluate_csharp_analysis", "evaluate_java_analysis", "evaluate_python_analysis", "evaluate_typescript_analysis"];
