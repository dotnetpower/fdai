#[derive(Clone, Debug, Default, PartialEq)]
pub struct DeclarativeInventoryConfig {
    pub fixture_path: String,
    pub known_resource_types: Vec<String>,
    pub known_link_types: Vec<String>,
    pub batch_size: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DeclarativeInventoryError {
    pub message: String,
}

impl DeclarativeInventoryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DeclarativeInventoryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DeclarativeInventoryError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DeclarativeInventory {
    pub initialized: bool,
}

impl DeclarativeInventory {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn full_snapshot(&self, mut since: Option<String>) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn delta(&self, mut cursor: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resource_count(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn link_count(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn iter_snapshot(&self) -> Vec<String> {
        let mut emitted: i64 = 0_i64;
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn iter_empty(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_fixture(mut path: String, mut known_resource_types: std::collections::BTreeSet<String>, mut known_link_types: std::collections::BTreeSet<String>) -> Result<(Vec<String>, Vec<String>), &'static str> {
    let mut seen_ids: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut resource_types_by_id: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let mut resources: Vec<String> = Vec::<String>::new();
    let mut links: Vec<String> = Vec::<String>::new();
    Ok((resources.clone(), links.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn batched(mut items: Vec<String>, mut size: i64) -> Vec<Vec<String>> {
    if items.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["DeclarativeInventory", "DeclarativeInventoryConfig", "DeclarativeInventoryError"];
