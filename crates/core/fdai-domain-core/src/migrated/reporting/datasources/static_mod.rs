#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StaticDataSource {
    pub initialized: bool,
}

impl StaticDataSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn name(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn query(&self, mut spec: String, mut since: String, mut until: String, mut variables: std::collections::BTreeMap<String, String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NoopDataSource {
    pub initialized: bool,
}

impl NoopDataSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn name(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn query(&self, mut spec: String, mut since: String, mut until: String, mut variables: std::collections::BTreeMap<String, String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["NoopDataSource", "StaticDataSource"];
