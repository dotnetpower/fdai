use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResumedInventoryCollection {
    pub attempt_id: String,
    pub manifest: String,
    pub checkpoint: BTreeMap<String, String>,
    pub resources: BTreeMap<String, String>,
    pub seen: Vec<String>,
}

impl ResumedInventoryCollection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.attempt_id.trim().is_empty() { return Err("attempt_id must be non-empty"); }
        if self.manifest.trim().is_empty() { return Err("manifest must be non-empty"); }
        Ok(())
    }
}

impl ResumedInventoryCollection {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn revalidate(&self, mut batch: String) -> Result<(String, String), &'static str> {
        let mut observed: Vec<String> = Vec::<String>::new();
        let mut additional: Vec<String> = Vec::<String>::new();
        Ok((String::new(), String::new()))
    }
}

