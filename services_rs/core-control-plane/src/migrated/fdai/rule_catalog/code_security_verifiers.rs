use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerifierLimits {
    pub max_file_bytes: i64,
    pub max_issues: i64,
}

impl VerifierLimits {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1000_i64..=10000000_i64).contains(&self.max_file_bytes) { return Err("max_file_bytes out of bounds"); }
        if !(1_i64..=100000_i64).contains(&self.max_issues) { return Err("max_issues out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Sink {
    pub call: Option<String>,
    pub method: Option<String>,
    pub arg: i64,
    pub require_keyword: BTreeMap<String, bool>,
    #[allow(clippy::type_complexity)]
    pub unsafe_unless_keyword: BTreeMap<String, Vec<String>>,
}

impl Sink {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(0_i64..=10_i64).contains(&self.arg) { return Err("arg out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerifierClass {
    pub sanitizers: Vec<String>,
    pub sinks: Vec<Sink>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PythonVerifier {
    pub entrypoint_decorators: Vec<String>,
    pub safe_parameter_annotations: Vec<String>,
    pub ignored_parameters: Vec<String>,
    pub request_roots: Vec<String>,
    pub request_attributes: Vec<String>,
    pub source_calls: Vec<String>,
    pub source_attributes: Vec<String>,
    pub global_sanitizers: Vec<String>,
    pub validators: Vec<String>,
    pub classes: BTreeMap<String, VerifierClass>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerifierPromotion {
    pub evidence: String,
    pub promoted: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerifierCatalog {
    pub schema_version: i64,
    pub catalog_id: String,
    pub version: String,
    pub promotion: Box<VerifierPromotion>,
    pub limits: Box<VerifierLimits>,
    pub python: Box<PythonVerifier>,
}

pub const DOTTED: &str = "^[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)*$";
pub const IDENT: &str = "^[A-Za-z_][A-Za-z0-9_]*$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Strict {
    pub initialized: bool,
}

impl Sink {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn one_target(&self) -> Result<Sink, &'static str> {
        if (self.call.is_none()) == (self.method.is_none()) {
            return Err("a sink names exactly one of call or method");
        }
        Ok(self.clone())
    }
}

impl VerifierCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn promoted(&self, mut key: String) -> bool {
        if key.is_empty() {
            return false;
        }
        false
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_verifier_catalog(mut root: String, mut known_classes: std::collections::BTreeSet<String>) -> Result<VerifierCatalog, &'static str> {
    if root.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["PythonVerifier", "Sink", "VerifierCatalog", "VerifierClass", "VerifierLimits", "VerifierPromotion", "load_verifier_catalog"];
