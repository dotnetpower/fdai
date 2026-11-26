use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProjectedResource {
    pub r#ref: String,
    pub properties: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InMemoryProjection {
    pub resources: BTreeMap<String, ProjectedResource>,
    pub evaluator: Option<String>,
}

impl InMemoryProjection {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn apply_diff(&self, mut diff: String) -> Result<InMemoryProjection, &'static str> {
        Ok(InMemoryProjection { evaluator: self.evaluator.clone(), ..Default::default() })
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn evaluate(&self, mut rules: String) -> Vec<String> {
        if rules.is_empty() {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn properties(&self, mut r#ref: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn contains(&self, mut r#ref: String) -> bool {
        if r#ref.is_empty() {
            return false;
        }
        false
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn build_baseline_projection(mut baseline: Vec<(String, std::collections::BTreeMap<String, String>)>, mut evaluator: Option<String>) -> Result<InMemoryProjection, &'static str> {
    let mut resources: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(InMemoryProjection { evaluator: evaluator.clone(), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["Evaluator", "InMemoryProjection", "build_baseline_projection"];
