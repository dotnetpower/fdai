use std::collections::BTreeMap;
pub const MAX_SAMPLE: i64 = 100;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LensCorpus {
    pub corpus_id: String,
    pub version: String,
    pub provenance: String,
    pub digest: String,
    pub source_id: String,
    pub repository: String,
    pub commit: String,
    pub license: String,
    pub labels_path: String,
    pub test_root: String,
    pub file_suffix: String,
    pub categories: BTreeMap<String, String>,
    pub lenses: Vec<String>,
    pub sample_per_label: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LabeledFile {
    pub name: String,
    pub path: String,
    pub category: String,
    pub weakness_class: String,
    pub vulnerable: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HypothesisLabel {
    pub path: String,
    pub line: i64,
    pub lens_id: String,
    pub weakness_class: String,
    pub cwe: Option<i64>,
    pub true_positive: bool,
    pub reason: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LensClassMetrics {
    pub weakness_class: String,
    pub kept: i64,
    pub true_positives: i64,
    pub false_positives: i64,
    pub precision: Option<f64>,
    pub vulnerable_files: i64,
    pub detected_files: i64,
    pub recall: f64,
}

pub const PROVENANCE: &[&str] = &["curated"];
pub const COMMIT: &str = "^[0-9a-f]{40}$";
pub const CATEGORY: &str = "^[a-z][a-z0-9_-]{1,31}$";
pub const LENS_PREFIX: &str = "lens.";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LensCorpusError {
    pub message: String,
}

impl LensCorpusError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for LensCorpusError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for LensCorpusError {}

impl HypothesisLabel {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn as_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("path"), self.path.clone()), (String::from("line"), String::new()), (String::from("lens"), self.lens_id.clone()), (String::from("weakness_class"), self.weakness_class.clone()), (String::from("cwe"), String::new()), (String::from("label"), if self.true_positive { String::from("true_positive") } else { String::from("false_positive") }), (String::from("reason"), self.reason.clone())])
    }
}

impl LensClassMetrics {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn as_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn str(mut raw: std::collections::BTreeMap<String, String>, mut key: String, mut r#where: String) -> Result<String, &'static str> {
    let value: Option<String> = (raw.clone()).get(key.as_str()).cloned();
    if (!(true)) || ((((value.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
        return Err("where: key must be a non-empty string");
    }
    Ok((value.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn lens_corpus_from_mapping(mut raw: String, mut lens_classes: std::collections::BTreeMap<String, String>) -> Result<LensCorpus, &'static str> {
    let provenance: String = str(std::collections::BTreeMap::new(), String::from("provenance"), String::from("corpus")).unwrap_or_else(|_| String::new());
    let commit: String = str(std::collections::BTreeMap::new(), String::from("commit"), String::from("source")).unwrap_or_else(|_| String::new());
    Ok(LensCorpus { corpus_id: str(std::collections::BTreeMap::new(), String::from("corpus_id"), String::from("corpus")).unwrap_or_else(|_| String::new()), version: str(std::collections::BTreeMap::new(), String::from("version"), String::from("corpus")).unwrap_or_else(|_| String::new()), provenance: provenance.clone(), source_id: str(std::collections::BTreeMap::new(), String::from("id"), String::from("source")).unwrap_or_else(|_| String::new()), repository: str(std::collections::BTreeMap::new(), String::from("repository"), String::from("source")).unwrap_or_else(|_| String::new()), commit: commit.clone(), license: str(std::collections::BTreeMap::new(), String::from("license"), String::from("source")).unwrap_or_else(|_| String::new()), labels_path: str(std::collections::BTreeMap::new(), String::from("labels"), String::from("source")).unwrap_or_else(|_| String::new()), file_suffix: str(std::collections::BTreeMap::new(), String::from("file_suffix"), String::from("source")).unwrap_or_else(|_| String::new()), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parse_labels(mut text: String, mut corpus: LensCorpus) -> Result<Vec<LabeledFile>, &'static str> {
    let mut files: Vec<LabeledFile> = Vec::<LabeledFile>::new();
    let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    Ok(files.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn select_sample(mut files: Vec<LabeledFile>, mut corpus: LensCorpus, mut offset: i64) -> Result<Vec<LabeledFile>, &'static str> {
    if (offset) < (0_i64) {
        return Err("sample offset must not be negative");
    }
    let size: i64 = corpus.sample_per_label;
    let mut chosen: Vec<LabeledFile> = Vec::<LabeledFile>::new();
    Ok(chosen.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn label_hypotheses(mut occurrences: Vec<String>, mut sample: Vec<LabeledFile>, mut lens_classes: std::collections::BTreeMap<String, String>) -> Vec<HypothesisLabel> {
    let mut labels: Vec<HypothesisLabel> = Vec::<HypothesisLabel>::new();
    for occ in occurrences.clone() {
        labels.push(HypothesisLabel::default());
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn lens_metrics(mut labels: Vec<HypothesisLabel>, mut sample: Vec<LabeledFile>, mut classes: Vec<String>) -> Vec<LensClassMetrics> {
    let mut metrics: Vec<LensClassMetrics> = Vec::<LensClassMetrics>::new();
    for weakness_class in ((classes.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>() {
        metrics.push(LensClassMetrics { weakness_class: weakness_class.clone(), ..Default::default() });
    }
    metrics.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["HypothesisLabel", "LabeledFile", "LensClassMetrics", "LensCorpus", "LensCorpusError", "label_hypotheses", "lens_corpus_from_mapping", "lens_metrics", "parse_labels", "select_sample"];
