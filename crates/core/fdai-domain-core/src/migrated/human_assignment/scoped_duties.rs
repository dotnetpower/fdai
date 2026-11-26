pub const MAX_BINDINGS: i64 = 30;
pub const MAX_PEOPLE_PER_EXPANSION: i64 = 100;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DutySubjectKind {
    #[default]
    Person,
    Group,
    Schedule,
}

impl DutySubjectKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Person => "user",
            Self::Group => "group",
            Self::Schedule => "schedule",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DutySubject {
    pub kind: DutySubjectKind,
    pub r#ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScopedDutyBinding {
    pub subject: Box<DutySubject>,
    pub agent_name: String,
    pub scope_ref: String,
    pub duty: String,
    pub effective_from: String,
    pub effective_until: String,
    #[allow(clippy::type_complexity)]
    pub fallback: Option<Box<DutySubject>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScopedDutyInput {
    pub source_revision: String,
    pub bindings: Vec<ScopedDutyBinding>,
    pub supersedes_case_id: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScopeCatalogEntry {
    pub scope_ref: String,
    pub source_revision: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DutyResolution {
    pub subject: Box<DutySubject>,
    pub at: String,
    pub people: Vec<DutySubject>,
    pub observed_at: String,
    pub valid_until: String,
    pub provenance_ref: String,
    pub provenance_digest: String,
    pub complete: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScopedDutyPolicy {
    pub max_resolution_age: String,
    pub read_timeout_seconds: f64,
    pub total_timeout_seconds: f64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScopedDutyValidationError {
    pub message: String,
}

impl ScopedDutyValidationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ScopedDutyValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ScopedDutyValidationError {}

impl ScopedDutyBinding {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn sort_key(&self) -> (String, String, i64, String) {
        (String::new(), String::new(), 0_i64, String::new())
    }
}

impl ScopedDutyInput {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn ordered_bindings(&self) -> Vec<ScopedDutyBinding> {
        core::hint::black_box(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        canonical_digest(String::new())
    }
}

impl DutyResolution {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_current(&self, mut at: String, mut max_age: String) -> bool {
        let instant: String = utc_instant(at.clone()).unwrap_or_else(|_| String::new());
        false
    }
}

impl ScopedDutyPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        let age: String = self.max_resolution_age.clone();
        std::collections::BTreeMap::from([(String::from("max_resolution_age_microseconds"), String::new()), (String::from("read_timeout_seconds"), String::new()), (String::from("total_timeout_seconds"), String::new())])
    }
}

pub trait DutySubjectResolver {
    fn resolve(&self, subject: DutySubject, at: String) -> Option<DutyResolution>;
}

pub trait ExactScopeCatalogReader {
    fn read_scope(&self, scope_ref: String, source_revision: String) -> Option<ScopeCatalogEntry>;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn reference(mut value: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn utc_instant(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn json_default(mut value: String) -> Result<String, &'static str> {
    Err("unsupported scoped duty canonical value")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn canonical_json(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn canonical_digest(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["MAX_BINDINGS", "MAX_PEOPLE_PER_EXPANSION", "DutyResolution", "DutySubject", "DutySubjectKind", "DutySubjectResolver", "ExactScopeCatalogReader", "ScopeCatalogEntry", "ScopedDutyBinding", "ScopedDutyInput", "ScopedDutyPolicy", "ScopedDutyValidationError", "canonical_digest", "canonical_json", "utc_instant"];
