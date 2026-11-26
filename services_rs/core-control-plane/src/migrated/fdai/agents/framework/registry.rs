#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PantheonRegistryError {
    pub message: String,
}

impl PantheonRegistryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PantheonRegistryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PantheonRegistryError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PantheonRegistry {
    pub initialized: bool,
}

impl PantheonRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn get(&self, mut name: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn all(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn owner_of_topic(&self, mut topic: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn owner_of_object_type(&self, mut object_type: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn names(&self) -> std::collections::BTreeSet<String> {
        std::collections::BTreeSet::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn assert_can_publish(&self, mut principal: String, mut topic: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn py_validate(mut specs: Vec<String>) -> Result<(), &'static str> {
    let mut issues: Vec<String> = Vec::<String>::new();
    let mut seen_names: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut owners_by_object_type: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let mut owners_by_topic: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    if !(issues.clone()).is_empty() {
        return Err(" .joinissues");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_pantheon() -> PantheonRegistry {
    core::hint::black_box(Default::default())
}

pub const PUBLIC_EXPORTS: &[&str] = &["PantheonRegistry", "PantheonRegistryError", "load_pantheon"];
