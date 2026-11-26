pub trait OperatorStateReader {
    fn read_state(&self, key: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StateStoreAksCommerceProjectionReader {
    pub initialized: bool,
}

impl StateStoreAksCommerceProjectionReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_latest(&self, mut service_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct UnavailableAksCommerceProjectionReader {
    pub initialized: bool,
}

impl UnavailableAksCommerceProjectionReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_latest(&self, mut service_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["StateStoreAksCommerceProjectionReader", "UnavailableAksCommerceProjectionReader"];
