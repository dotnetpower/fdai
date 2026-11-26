use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScannerSpec {
    pub producer: String,
    pub argv: Vec<String>,
    pub mounts: Vec<String>,
    pub cache_env: Option<String>,
    pub success_exit_codes: Vec<i64>,
    pub timeout_seconds: i64,
    pub max_output_bytes: i64,
    pub address_space_bytes: Option<i64>,
}

impl ScannerSpec {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(10_i64..=3600_i64).contains(&self.timeout_seconds) { return Err("timeout_seconds out of bounds"); }
        if !(1000_i64..=50000000_i64).contains(&self.max_output_bytes) { return Err("max_output_bytes out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScannerCatalog {
    pub schema_version: i64,
    pub catalog_id: String,
    pub version: String,
    pub scanners: BTreeMap<String, ScannerSpec>,
}

pub const PLACEHOLDER: &str = "\\{([^{}]*)\\}";
impl ScannerSpec {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn placeholders(&self) -> Result<ScannerSpec, &'static str> {
        let used: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
        for value in self.argv.clone() {
            if ((value.clone()).is_empty()) || ((value.clone()).contains("\0")) {
                return Err("argv entries must be non-empty and NUL-free");
            }
        }
        if !((used.clone()).contains("source")) {
            return Err("argv must reference source");
        }
        if ((self.cache_env.clone()).is_some()) && (!((self.mounts.clone()).contains(&(String::from("cache"))))) {
            return Err("cache_env requires the cache mount");
        }
        Ok(self.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_scanner_catalog(mut root: String) -> Result<ScannerCatalog, &'static str> {
    if root.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn resolve_argv(mut spec: ScannerSpec, mut mounts: std::collections::BTreeMap<String, String>) -> Result<Vec<String>, &'static str> {
    let mut resolved: Vec<String> = Vec::<String>::new();
    for value in spec.argv.clone() {
        resolved.push(value.clone());
    }
    Ok(resolved.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ScannerCatalog", "ScannerSpec", "load_scanner_catalog", "resolve_argv"];
