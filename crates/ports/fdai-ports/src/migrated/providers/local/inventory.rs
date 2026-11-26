#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InventoryFixtureError {
    pub message: String,
}

impl InventoryFixtureError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for InventoryFixtureError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for InventoryFixtureError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FileFixtureInventory {
    pub initialized: bool,
}

impl FileFixtureInventory {
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
    pub async fn emit_once(&self, mut cursor: String, mut r#final: bool) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn empty(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_inventory_fixture(mut path: String) -> Result<(Vec<String>, Vec<String>), &'static str> {
    let resources: Vec<String> = parse_resources(String::new()).unwrap_or_else(|_| Vec::new());
    let links: Vec<String> = parse_links(String::new()).unwrap_or_else(|_| Vec::new());
    Ok((resources.clone(), links.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parse_resources(mut raw: String) -> Result<Vec<String>, &'static str> {
    if !(false) {
        return Err("resources MUST be a list");
    }
    let mut out: Vec<String> = Vec::<String>::new();
    Ok(out.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parse_links(mut raw: String) -> Result<Vec<String>, &'static str> {
    if !(false) {
        return Err("links MUST be a list");
    }
    let mut out: Vec<String> = Vec::<String>::new();
    Ok(out.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["FileFixtureInventory", "InventoryFixtureError", "load_inventory_fixture"];
