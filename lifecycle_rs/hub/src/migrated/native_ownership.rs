pub const NATIVE_ENTITY_KIND: &str = "native-workload-scope";
pub const ACTION: &str = "entity.native_creation_accepted";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NativeOwnershipError {
    pub message: String,
}

impl NativeOwnershipError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for NativeOwnershipError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for NativeOwnershipError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NativeOwnershipStore {
    pub initialized: bool,
}

impl NativeOwnershipStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn accept(&self, mut installation_id: String, mut command: String, mut operator: String, mut now: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::from([(String::from("changed"), String::new()), (String::from("claim_digest"), String::new())]))
    }
}

