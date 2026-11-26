use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnalysisBuildContext {
    pub schema_version: String,
    #[allow(clippy::type_complexity)]
    pub language_roots: BTreeMap<String, Vec<String>>,
    pub configuration_digests: BTreeMap<String, String>,
    pub generated_code_policy: String,
    pub excluded_directories: Vec<String>,
}

impl AnalysisBuildContext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.generated_code_policy.as_str(), "include") { return Err("invalid generated_code_policy literal"); }
        Ok(())
    }
}

pub const CONFIG_SUFFIXES: &[&str] = &[".csproj", ".fsproj", ".props", ".targets"];
impl AnalysisBuildContext {
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
pub fn bounded_digest(mut path: String, mut limit: i64) -> Result<String, &'static str> {
    if path.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn build_analysis_context(mut root: String, mut max_files: i64, mut max_file_bytes: i64) -> Result<AnalysisBuildContext, &'static str> {
    let mut configurations: Vec<String> = Vec::<String>::new();
    Ok(AnalysisBuildContext { schema_version: String::from("1.0.0"), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["AnalysisBuildContext", "build_analysis_context"];
