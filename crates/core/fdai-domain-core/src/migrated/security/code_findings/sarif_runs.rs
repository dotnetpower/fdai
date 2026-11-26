pub const MAX_ARTIFACTS: i64 = 50000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RunMetadata {
    pub producer: String,
    pub version: String,
    pub declared_rules_digest: String,
    pub execution_successful: Option<bool>,
    pub truncated: bool,
    pub analyzed_paths: Vec<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn run_metadata(mut run: std::collections::BTreeMap<String, String>, mut producer: String, mut version: String, mut rule_ids: Vec<String>, mut normalize: String) -> RunMetadata {
    let invocations: Option<String> = (run.clone()).get("invocations").cloned();
    let properties: Option<String> = (run.clone()).get("properties").cloned();
    let artifacts: Option<String> = (run.clone()).get("artifacts").cloned();
    let mut paths: Vec<String> = Vec::<String>::new();
    RunMetadata { producer: producer.clone(), version: version.clone(), analyzed_paths: ((paths.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>(), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["RunMetadata", "run_metadata"];
