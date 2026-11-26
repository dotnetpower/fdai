use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExpectedIssue {
    pub weakness_class: String,
    pub path: String,
    pub line: i64,
    pub occurrence_ids: Vec<String>,
    pub reviewer_band: Option<String>,
    pub facts: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EvaluationCase {
    pub case_id: String,
    pub exposure: String,
    pub occurrences: Vec<String>,
    pub expected: Vec<ExpectedIssue>,
    pub split: String,
    pub kind: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EvaluationCorpus {
    pub corpus_id: String,
    pub version: String,
    pub provenance: String,
    pub digest: String,
    pub line_shift: i64,
    pub acceptance: BTreeMap<String, f64>,
    pub cases: Vec<EvaluationCase>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EvaluationMetrics {
    pub cases: i64,
    pub expected_issues: i64,
    pub produced_issues: i64,
    pub dedup_precision: f64,
    pub dedup_recall: f64,
    pub false_merge_pairs: i64,
    pub false_split_pairs: i64,
    pub detection_precision: f64,
    pub detection_recall: f64,
    pub severity_range_pairs: i64,
    pub severity_range_containment: f64,
    pub severity_pairs: i64,
    pub severity_exact_agreement: f64,
    pub severity_weighted_kappa: f64,
    pub line_shift_tracking: f64,
    pub stable: bool,
    pub misses: Vec<String>,
}

pub const EVALUATION_REVISION: &str = "0000000000000000000000000000000000000000";
pub const PROVENANCE: &[&str] = &["synthetic", "curated"];
pub const SPLITS: &[&str] = &["dev", "holdout"];
pub const KINDS: &[&str] = &["code", "dependency"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EvaluationCorpusError {
    pub message: String,
}

impl EvaluationCorpusError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for EvaluationCorpusError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for EvaluationCorpusError {}

impl EvaluationMetrics {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn as_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn ratio(mut numerator: i64, mut denominator: i64) -> f64 {
    0.0_f64
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn pairs(mut groups: Vec<std::collections::BTreeSet<String>>) -> std::collections::BTreeSet<std::collections::BTreeSet<String>> {
    std::collections::BTreeSet::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn weighted_kappa(mut pairs: Vec<(String, String)>) -> f64 {
    if (pairs.clone()).is_empty() {
        return 1.0;
    }
    let n: f64 = (((pairs.clone()).len() as i64)) as f64;
    0.0_f64
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn matches(mut expected: ExpectedIssue, mut issue: String) -> bool {
    if issue.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn shifted(mut occurrences: Vec<String>, mut offset: i64) -> Vec<String> {
    let mut shifted: Vec<String> = Vec::<String>::new();
    shifted.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn evaluate(mut corpus: EvaluationCorpus, mut catalog: String) -> EvaluationMetrics {
    let mut severity: Vec<(String, String)> = Vec::<(String, String)>::new();
    let mut misses: Vec<String> = Vec::<String>::new();
    let mut stable: bool = true;
    for case in corpus.cases.clone() {
        let truth: std::collections::BTreeSet<std::collections::BTreeSet<String>> = pairs(Vec::new());
        let produced: std::collections::BTreeSet<std::collections::BTreeSet<String>> = pairs(Vec::new());
        let mut facts: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        let mut matched: std::collections::BTreeMap<i64, String> = std::collections::BTreeMap::<i64, String>::new();
    }
    EvaluationMetrics { cases: ((corpus.cases.clone()).len() as i64), dedup_precision: ratio(0_i64, 0_i64), dedup_recall: ratio(0_i64, 0_i64), detection_precision: ratio(0_i64, 0_i64), detection_recall: ratio(0_i64, 0_i64), severity_range_containment: ratio(0_i64, 0_i64), severity_pairs: ((severity.clone()).len() as i64), severity_exact_agreement: ratio(0_i64, ((severity.clone()).len() as i64)), severity_weighted_kappa: weighted_kappa(severity.clone()), line_shift_tracking: ratio(0_i64, 0_i64), stable: stable, misses: misses.clone(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn split_corpus(mut corpus: EvaluationCorpus, mut split: String) -> Option<EvaluationCorpus> {
    if split.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn kind_corpus(mut corpus: EvaluationCorpus, mut kind: String) -> Option<EvaluationCorpus> {
    if kind.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn acceptance_failures(mut metrics: EvaluationMetrics, mut acceptance: std::collections::BTreeMap<String, f64>) -> Vec<String> {
    if acceptance.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn str(mut raw: std::collections::BTreeMap<String, String>, mut key: String, mut r#where: String) -> Result<String, &'static str> {
    let value: Option<String> = (raw.clone()).get(key.as_str()).cloned();
    if (!(true)) || (!((value.clone()).is_some())) {
        return Err("where: key must be a non-empty string");
    }
    Ok((value.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn strings(mut raw: std::collections::BTreeMap<String, String>, mut key: String, mut r#where: String) -> Result<Vec<String>, &'static str> {
    if raw.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn int(mut raw: std::collections::BTreeMap<String, String>, mut key: String, mut r#where: String) -> Result<i64, &'static str> {
    let value: Option<String> = (raw.clone()).get(key.as_str()).cloned();
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn facts(mut raw: String, mut r#where: String) -> Result<Option<String>, &'static str> {
    if false {
        return Ok(None);
    }
    if !(false) {
        return Err("where: facts must be a mapping");
    }
    Ok(None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn occurrence(mut raw: String, mut r#where: String) -> Result<String, &'static str> {
    if !(false) {
        return Err("where: occurrence must be a mapping");
    }
    let producer: String = str(std::collections::BTreeMap::new(), String::from("producer"), r#where.clone()).unwrap_or_else(|_| String::new());
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn expected(mut raw: String, mut r#where: String, mut known: std::collections::BTreeSet<String>) -> Result<ExpectedIssue, &'static str> {
    if !(false) {
        return Err("where: expected issue must be a mapping");
    }
    let ids: std::collections::BTreeSet<String> = (strings(std::collections::BTreeMap::new(), String::from("occurrences"), r#where.clone()).unwrap_or_else(|_| Vec::new())).into_iter().collect::<std::collections::BTreeSet<String>>();
    Ok(ExpectedIssue { weakness_class: str(std::collections::BTreeMap::new(), String::from("weakness_class"), r#where.clone()).unwrap_or_else(|_| String::new()), path: str(std::collections::BTreeMap::new(), String::from("path"), r#where.clone()).unwrap_or_else(|_| String::new()), line: int(std::collections::BTreeMap::new(), String::from("line"), r#where.clone()).unwrap_or_else(|_| 0_i64), facts: facts(String::new(), r#where.clone()).unwrap_or_else(|_| None), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn corpus_from_mapping(mut raw: String) -> Result<EvaluationCorpus, &'static str> {
    let provenance: String = str(std::collections::BTreeMap::new(), String::from("provenance"), String::from("corpus")).unwrap_or_else(|_| String::new());
    let mut cases: Vec<EvaluationCase> = Vec::<EvaluationCase>::new();
    let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    Ok(EvaluationCorpus { corpus_id: str(std::collections::BTreeMap::new(), String::from("corpus_id"), String::from("corpus")).unwrap_or_else(|_| String::new()), version: str(std::collections::BTreeMap::new(), String::from("version"), String::from("corpus")).unwrap_or_else(|_| String::new()), provenance: provenance.clone(), cases: cases.clone(), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["EVALUATION_REVISION", "KINDS", "EvaluationCase", "EvaluationCorpus", "EvaluationCorpusError", "EvaluationMetrics", "ExpectedIssue", "acceptance_failures", "corpus_from_mapping", "evaluate", "kind_corpus", "split_corpus", "weighted_kappa"];
