#[derive(Clone, Debug, Default, PartialEq)]
pub struct Provenance {
    pub created_at: String,
    pub created_by: String,
    pub source: Option<String>,
}

impl Provenance {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.created_at.trim().is_empty() { return Err("created_at must be non-empty"); }
        if self.created_by.trim().is_empty() { return Err("created_by must be non-empty"); }
        Ok(())
    }
}

impl Provenance {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<Provenance, &'static str> {
        let source: Option<String> = (raw.clone()).get("source").cloned();
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["Provenance"];
