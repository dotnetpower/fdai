use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnalysisEvaluationCase {
    pub case_id: String,
    pub split: String,
    pub vulnerable: bool,
    pub files: BTreeMap<String, String>,
}

impl AnalysisEvaluationCase {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.split.as_str(), "dev" | "holdout") { return Err("invalid split literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnalysisEvaluationCorpus {
    pub schema_version: String,
    pub corpus_id: String,
    pub language: String,
    pub version: String,
    pub rule_id: String,
    pub cases: Vec<AnalysisEvaluationCase>,
}

impl AnalysisEvaluationCorpus {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.language.as_str(), "csharp" | "java" | "python" | "typescript") { return Err("invalid language literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Strict {
    pub initialized: bool,
}

impl AnalysisEvaluationCase {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn safe_paths(mut value: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(value.clone())
    }
}

impl AnalysisEvaluationCorpus {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn balanced_splits(&self) -> Result<AnalysisEvaluationCorpus, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn canonical_bytes(&self) -> Vec<u8> {
        core::hint::black_box(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_analysis_evaluation_corpus(mut root: String, mut name: String) -> Result<AnalysisEvaluationCorpus, &'static str> {
    if (!((!((name.clone()).replace("-", "")).is_empty() && ((name.clone()).replace("-", "")).chars().all(|c| c.is_ascii_alphanumeric())))) || ((name.clone()).starts_with("-")) {
        return Err("invalid analysis evaluation corpus name");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["AnalysisEvaluationCase", "AnalysisEvaluationCorpus", "load_analysis_evaluation_corpus"];
