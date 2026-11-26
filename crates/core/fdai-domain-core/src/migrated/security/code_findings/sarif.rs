#[derive(Clone, Debug, Default, PartialEq)]
pub struct SarifLimits {
    pub max_bytes: i64,
    pub max_depth: i64,
    pub max_runs: i64,
    pub max_results: i64,
    pub max_locations_per_result: i64,
    pub max_code_flows_per_result: i64,
    pub max_flow_steps: i64,
    pub max_text: i64,
    pub max_identifier: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SarifIngestContext {
    pub lane: String,
    pub revision: String,
    pub source_roots: Vec<String>,
    pub limits: Box<SarifLimits>,
    pub producer: Option<String>,
    pub trusted_analysis_evidence: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DroppedResult {
    pub run_index: i64,
    pub result_index: i64,
    pub reason: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SarifIngestResult {
    pub scan_digest: String,
    pub producers: Vec<String>,
    pub occurrences: Vec<String>,
    pub dropped: Vec<DroppedResult>,
    pub runs: Vec<String>,
}

pub const REVISION: &str = "^[0-9a-f]{40}([0-9a-f]{24})?$";
pub const CWE: &str = "(?i)\\bcwe[-_/ ]?0*(\\d{1,5})\\b";
pub const DRIVE: &str = "^[A-Za-z]:";
pub const PACKAGE_KEYS: &[&str] = &["purl", "packageName", "package", "PkgName", "pkgName"];
pub const VERSION_KEYS: &[&str] = &["installedVersion", "InstalledVersion", "packageVersion", "version"];
pub const DIGEST: &str = "^sha256:[0-9a-f]{64}$";
pub const VERSION: &str = "^\\d+\\.\\d+\\.\\d+$";
pub const IDENTIFIER: &str = "^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$";
pub const FLOW_ROLES: &[&str] = &["source", "flow", "call", "return", "sanitizer", "sink"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SarifIngestError {
    pub message: String,
}

impl SarifIngestError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SarifIngestError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SarifIngestError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn clean_text(mut value: String, mut limit: i64) -> String {
    if !(true) {
        return String::from("");
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn check_depth(mut raw: Vec<u8>, mut max_depth: i64) -> Result<(), &'static str> {
    let mut depth: i64 = 0_i64;
    let mut in_string: bool = false;
    let mut escaped: bool = false;
    for byte in raw.clone() {
        if in_string {
            if escaped {
                escaped = false;
            }
        }
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn normalize_path(mut uri: String, mut source_roots: Vec<String>) -> Option<String> {
    if (!(true)) || (((uri.clone()).is_empty()) || ((((uri.clone()).len() as i64)) > (2048_i64))) {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn strip_drive_slash(mut path: String) -> String {
    if path.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn relativize(mut path: String, mut source_roots: Vec<String>) -> Option<String> {
    let candidate: String = strip_drive_slash(String::new());
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn as_list(mut value: String, mut limit: i64) -> Vec<String> {
    if value.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn as_map(mut value: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn line(mut value: String) -> Option<i64> {
    if value.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn physical(mut location: String, mut ctx: SarifIngestContext) -> (Option<String>, Option<i64>, Option<i64>) {
    let physical: std::collections::BTreeMap<String, String> = as_map(String::new());
    let artifact: std::collections::BTreeMap<String, String> = as_map(String::new());
    let region: std::collections::BTreeMap<String, String> = as_map(String::new());
    let path: Option<String> = normalize_path(String::new(), ctx.source_roots.clone());
    let start: Option<i64> = line(String::new());
    (None, None, None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn tags(mut sources: Vec<String>) -> Vec<String> {
    let mut tags: Vec<String> = Vec::<String>::new();
    for source in sources.clone() {
        for tag in as_list(String::new(), 64_i64) {
            let text: String = clean_text(tag.clone(), 128_i64);
            if (!(text.clone()).is_empty()) && (!((tags.clone()).contains(&(text.clone())))) {
                tags.push(text.clone());
            }
        }
    }
    tags.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn cwes(mut tags: Vec<String>, mut result: std::collections::BTreeMap<String, String>) -> Vec<i64> {
    let mut found: Vec<i64> = Vec::<i64>::new();
    let mut texts: Vec<String> = tags.clone();
    for taxon in as_list(String::new(), 16_i64) {
        texts.push(clean_text(String::new(), 32_i64));
    }
    if (found.clone()).is_empty() {
        for taxon in as_list(String::new(), 16_i64) {
            let taxon_map: std::collections::BTreeMap<String, String> = as_map(taxon.clone());
            let component: std::collections::BTreeMap<String, String> = as_map(String::new());
            let identifier: String = clean_text(String::new(), 16_i64);
            if (((clean_text(String::new(), 16_i64)).to_uppercase()) == (String::from("CWE"))) && ((!(identifier.clone()).is_empty() && (identifier.clone()).chars().all(|c| c.is_ascii_digit()))) {
                found.push((identifier.clone()).trim().parse::<i64>().unwrap_or(0));
            }
        }
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn advisories(mut texts: Vec<String>) -> Vec<String> {
    let mut found: Vec<String> = Vec::<String>::new();
    found.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn score(mut value: String) -> Option<f64> {
    if value.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn first_text(mut props: std::collections::BTreeMap<String, String>, mut keys: Vec<String>, mut limit: i64) -> Option<String> {
    for key in keys.clone() {
        let text: String = clean_text(String::new(), limit);
        if !(text.clone()).is_empty() {
            return Some(text.clone());
        }
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn ingest_sarif(mut raw: Vec<u8>, mut ctx: SarifIngestContext) -> Result<SarifIngestResult, &'static str> {
    let limits: SarifLimits = *(ctx.limits.clone());
    if (((raw.clone()).len() as i64)) > (limits.max_bytes) {
        return Err("SARIF exceeds limits.max_bytes bytes");
    }
    let _ = check_depth(raw.clone(), limits.max_depth).unwrap_or_else(|_| ());
    let mut occurrences: Vec<String> = Vec::<String>::new();
    let mut dropped: Vec<DroppedResult> = Vec::<DroppedResult>::new();
    let mut producers: Vec<String> = Vec::<String>::new();
    let mut run_facts: Vec<String> = Vec::<String>::new();
    let mut total: i64 = 0_i64;
    Ok(SarifIngestResult::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn occurrence(mut result: std::collections::BTreeMap<String, String>, mut rules: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, mut producer: String, mut version: String, mut scan_digest: String, mut run_index: i64, mut result_index: i64, mut ctx: SarifIngestContext) -> String {
    let limits: SarifLimits = *(ctx.limits.clone());
    if !(as_list(String::new(), 1_i64)).is_empty() {
        return String::from("suppressed_by_producer");
    }
    let rule_id: String = clean_text(String::new(), limits.max_identifier);
    if (rule_id.clone()).is_empty() {
        return String::from("missing_rule_id");
    }
    let rule: std::collections::BTreeMap<String, String> = (rules.clone()).get(rule_id.as_str()).cloned().unwrap_or_else(|| std::collections::BTreeMap::<String, String>::new());
    let locations: Vec<String> = as_list(String::new(), limits.max_locations_per_result);
    if (locations.clone()).is_empty() {
        return String::from("missing_location");
    }
    let logical_locations: Vec<String> = as_list(String::new(), 1_i64);
    let logical: std::collections::BTreeMap<String, String> = if !(logical_locations.clone()).is_empty() { as_map(String::new()) } else { std::collections::BTreeMap::<String, String>::new() };
    let symbol: Option<String> = (Some(clean_text(String::new(), limits.max_identifier))).or_else(|| None);
    let tags: Vec<String> = tags(Vec::new());
    let props: std::collections::BTreeMap<String, String> = as_map(String::new());
    let rule_props: std::collections::BTreeMap<String, String> = as_map(String::new());
    let level: String = clean_text(String::new(), 16_i64);
    let advisories: Vec<String> = advisories(Vec::new());
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn flow(mut result: std::collections::BTreeMap<String, String>, mut ctx: SarifIngestContext) -> Vec<String> {
    let limits: SarifLimits = *(ctx.limits.clone());
    for flow in as_list(String::new(), limits.max_code_flows_per_result) {
        for thread in as_list(String::new(), 4_i64) {
            let mut steps: Vec<String> = Vec::<String>::new();
            for step in as_list(String::new(), limits.max_flow_steps) {
                let record: std::collections::BTreeMap<String, String> = as_map(step.clone());
            }
            if !(steps.clone()).is_empty() {
                return steps.clone();
            }
        }
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn analysis_evidence(mut properties: std::collections::BTreeMap<String, String>, mut limits: SarifLimits) -> Option<String> {
    let path_id: String = clean_text(String::new(), limits.max_identifier);
    let path_digest: String = clean_text(String::new(), 71_i64);
    let graph_digest: String = clean_text(String::new(), 71_i64);
    let graph_schema: String = clean_text(String::new(), 32_i64);
    let path_schema: String = clean_text(String::new(), 32_i64);
    let rule_version: String = clean_text(String::new(), 32_i64);
    let raw_frontends: Option<String> = (properties.clone()).get("fdaiFrontendVersions").cloned();
    let raw_coverage: Option<String> = (properties.clone()).get("fdaiCoverageLimits").cloned();
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["DroppedResult", "SarifIngestContext", "SarifIngestError", "SarifIngestResult", "SarifLimits", "clean_text", "ingest_sarif", "normalize_path"];
