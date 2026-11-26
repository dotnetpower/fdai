#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EmptyAuthStateLoader {
    pub initialized: bool,
}

impl EmptyAuthStateLoader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn load(&self, mut auth_profile_ref: String) -> Option<std::collections::BTreeMap<String, String>> {
        if !self.initialized {
            return None;
        }
        None
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReadOnlyRequestGate {
    pub initialized: bool,
}

impl ReadOnlyRequestGate {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn authorize(&mut self, mut method: String, mut url: String, mut redirect_from: Option<String>) -> bool {
        let normalized_method: String = method.to_uppercase();
        if !(matches!(normalized_method.as_str(), "GET" | "HEAD")) {
            return false;
        }
        true
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IsolatedBrowserEvidenceProvider {
    pub initialized: bool,
}

impl IsolatedBrowserEvidenceProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn capture(&self, mut policy: String, mut request: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["IsolatedBrowserEvidenceProvider"];
