pub const PROMOTION_LOCK: i64 = 732410991;

pub trait InventorySnapshotConnectionConfig {
    fn dsn(&self) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresInventoryAgeProvider {
    pub initialized: bool,
}

impl PostgresInventoryAgeProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn call(&self, mut resource_ref: String) -> Option<i64> {
        if !self.initialized {
            return None;
        }
        None
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresInventoryContextProvider {
    pub initialized: bool,
}

impl PostgresInventoryContextProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn call(&self, mut resource_ref: String) -> Option<std::collections::BTreeMap<String, String>> {
        if !self.initialized {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["_PROMOTION_LOCK", "PostgresInventoryAgeProvider", "PostgresInventoryContextProvider"];
