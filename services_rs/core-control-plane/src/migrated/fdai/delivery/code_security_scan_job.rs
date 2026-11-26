use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScanJobConfig {
    pub repository: String,
    pub revision: String,
    pub repository_alias: String,
    pub work_root: String,
    pub executables: BTreeMap<String, String>,
    pub rules_dir: String,
    pub cache_dir: Option<String>,
    pub exposure: String,
    #[allow(clippy::type_complexity)]
    pub required_scanners: Option<Vec<String>>,
    pub known_exploited: Vec<String>,
    pub local_path: Option<String>,
    pub include_uncommitted: bool,
    pub source: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScanJobResult {
    pub revision: String,
    pub tree_id: String,
    pub issues: Vec<String>,
    pub receipt: String,
    pub package: BTreeMap<String, String>,
    pub runs: Vec<String>,
    pub coverage_limits: Vec<String>,
    pub published: bool,
    pub artifact_dir: String,
    pub sarif_files: Vec<String>,
    pub analysis_results: Vec<String>,
    pub analysis_incremental_plans: Vec<String>,
    pub analysis_cache_notes: Vec<String>,
    pub lens_report: Option<String>,
    pub verifier_results: Vec<String>,
    pub proof_results: Vec<String>,
    pub revision_kind: String,
    pub source_path: Option<String>,
}

pub trait ReviewPublisher {
    fn publish_code_security_drift(&self, package: std::collections::BTreeMap<String, String>) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub async fn run_scan_job(mut config: ScanJobConfig, mut catalog: String, mut scanners: String, mut acquirer: Option<String>, mut sandbox: String, mut prepared_source: Option<String>, mut publisher: Option<String>, mut lens_catalog: Option<String>, mut lens_models: Vec<String>, mut verifier_catalog: Option<String>, mut prove_python: Option<String>, mut prove_runtimes: Option<std::collections::BTreeMap<String, String>>, mut analysis_rules: Vec<String>, mut typescript_frontend: Option<String>, mut java_compiler: Option<String>, mut csharp_compiler: Option<String>) -> Result<ScanJobResult, &'static str> {
    if prepared_source.is_some() {
        if (acquirer.is_some()) || (((config.local_path.clone()).is_some()) || (!(config.repository.clone()).is_empty())) {
            return Err("prepared scanning cannot also acquire source");
        }
        if (publisher.is_some()) || (!(lens_models.clone()).is_empty()) {
            return Err("prepared scanning cannot publish or call live lenses");
        }
    } else {
        let Some(mut acquirer) = acquirer.clone() else { return Err("scanning requires a source acquirer"); };
    }
    let mut limits: Vec<String> = Vec::<String>::new();
    let mut runs: Vec<String> = Vec::<String>::new();
    let mut ingested: Vec<String> = Vec::<String>::new();
    let mut observed: std::collections::BTreeMap<String, bool> = std::collections::BTreeMap::<String, bool>::new();
    let mut sarif_files: Vec<String> = Vec::<String>::new();
    let mut analysis_results: Vec<String> = Vec::<String>::new();
    let mut analysis_incremental_plans: Vec<String> = Vec::<String>::new();
    let mut analysis_cache_notes: Vec<String> = Vec::<String>::new();
    let mut analysis_versions: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let lens_report: Option<String> = None;
    let mut lens_notes: Vec<String> = Vec::<String>::new();
    let mut lens_found: Vec<String> = Vec::<String>::new();
    let proof_enabled: bool = (prove_python.is_some()) || ((prove_runtimes.clone()).is_some());
    Ok(ScanJobResult { runs: runs.clone(), coverage_limits: limits.clone(), sarif_files: sarif_files.clone(), analysis_results: analysis_results.clone(), analysis_incremental_plans: analysis_incremental_plans.clone(), analysis_cache_notes: analysis_cache_notes.clone(), lens_report: lens_report.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rules_digest(mut rules_dir: String) -> String {
    if rules_dir.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn digest_values(mut values: Vec<String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn analysis_rules_digest(mut rules: Vec<String>) -> String {
    if rules.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn analysis_cache_path(mut work_root: String, mut repository_alias: String, mut rule_id: String) -> String {
    if work_root.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn has_typescript_source(mut root: String) -> bool {
    if root.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn has_python_source(mut root: String) -> bool {
    if root.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn has_java_source(mut root: String) -> bool {
    if root.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn has_csharp_source(mut root: String) -> bool {
    if root.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rules_versions(mut ingested: Vec<String>, mut scanners: String, mut digest: String) -> std::collections::BTreeMap<String, String> {
    let versions: std::collections::BTreeMap<String, std::collections::BTreeSet<String>> = std::collections::BTreeMap::<String, std::collections::BTreeSet<String>>::new();
    let mut resolved: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([]);
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn sarif_specs(mut result: ScanJobResult) -> Vec<String> {
    core::hint::black_box(Vec::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ReviewPublisher", "ScanJobConfig", "ScanJobResult", "rules_digest", "run_scan_job", "sarif_specs"];
