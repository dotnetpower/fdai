#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArmSubmission {
    pub status_url: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ArmClient {
    pub initialized: bool,
}

impl ArmClient {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn request(&self, mut method: String, mut path: String, mut api_version: String, mut json_body: Option<std::collections::BTreeMap<String, String>>, mut executor: bool, mut request_headers: Option<std::collections::BTreeMap<String, String>>) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn poll_status(&self, mut status_url: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn validate_status_url(&self, mut status_url: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn retry_after_seconds(mut response: String) -> f64 {
    0.0_f64
}

