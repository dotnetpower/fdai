pub trait SchemaRegistry {
    fn get(&self, name: String, version: Option<String>) -> std::collections::BTreeMap<String, String>;
    fn names(&self) -> Vec<String>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SchemaNotFoundError {
    pub message: String,
}

impl SchemaNotFoundError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SchemaNotFoundError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SchemaNotFoundError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PackageResourceSchemaRegistry {
    pub initialized: bool,
}

impl PackageResourceSchemaRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn get(&self, mut name: String, mut version: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        let target_version: Option<String> = (version.clone()).or_else(|| self.latest_version(name.clone()));
        let Some(mut target_version) = target_version.clone() else { return Err("unknown schema name: namer"); };
        Ok(std::collections::BTreeMap::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn names(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn latest_version(&self, mut name: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn semver_key(mut v: String) -> (i64, i64, i64) {
    (0_i64, 0_i64, 0_i64)
}

pub const PUBLIC_EXPORTS: &[&str] = &["PackageResourceSchemaRegistry", "SchemaNotFoundError", "SchemaRegistry"];
