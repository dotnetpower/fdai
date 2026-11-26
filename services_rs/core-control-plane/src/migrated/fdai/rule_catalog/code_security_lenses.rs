use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct LensLimits {
    pub max_candidates_per_lens: i64,
    pub max_model_calls: i64,
    pub excerpt_radius: i64,
    pub max_excerpt_bytes: i64,
    pub max_file_bytes: i64,
    pub max_files: i64,
    pub max_findings_per_response: i64,
    pub quorum: i64,
    pub line_tolerance: i64,
}

impl LensLimits {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=500_i64).contains(&self.max_candidates_per_lens) { return Err("max_candidates_per_lens out of bounds"); }
        if !(1_i64..=5000_i64).contains(&self.max_model_calls) { return Err("max_model_calls out of bounds"); }
        if !(3_i64..=200_i64).contains(&self.excerpt_radius) { return Err("excerpt_radius out of bounds"); }
        if !(500_i64..=100000_i64).contains(&self.max_excerpt_bytes) { return Err("max_excerpt_bytes out of bounds"); }
        if !(1000_i64..=5000000_i64).contains(&self.max_file_bytes) { return Err("max_file_bytes out of bounds"); }
        if !(1_i64..=100000_i64).contains(&self.max_files) { return Err("max_files out of bounds"); }
        if !(1_i64..=20_i64).contains(&self.max_findings_per_response) { return Err("max_findings_per_response out of bounds"); }
        if !(2_i64..=5_i64).contains(&self.quorum) { return Err("quorum out of bounds"); }
        if !(0_i64..=10_i64).contains(&self.line_tolerance) { return Err("line_tolerance out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Lens {
    pub weakness_class: String,
    pub cwe: Vec<i64>,
    pub languages: Vec<String>,
    pub sink_hints: Vec<String>,
    pub focus: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LensCatalog {
    pub schema_version: i64,
    pub catalog_id: String,
    pub version: String,
    pub system_prompt: String,
    pub limits: Box<LensLimits>,
    #[allow(clippy::type_complexity)]
    pub languages: BTreeMap<String, Vec<String>>,
    pub lenses: BTreeMap<String, Lens>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Strict {
    pub initialized: bool,
}

impl Lens {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn hints_compile(&self) -> Result<Lens, &'static str> {
        Err("runtime_binding_required")
    }
}

impl LensCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn known_languages(&self) -> Result<LensCatalog, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn language_for(&self, mut path: String) -> Option<String> {
        if path.is_empty() {
            return None;
        }
        None
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_lens_catalog(mut root: String) -> Result<LensCatalog, &'static str> {
    if root.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["Lens", "LensCatalog", "LensLimits", "load_lens_catalog"];
