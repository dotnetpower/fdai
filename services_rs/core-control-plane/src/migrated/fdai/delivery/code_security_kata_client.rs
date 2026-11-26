#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct KataApiError {
    pub message: String,
}

impl KataApiError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for KataApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for KataApiError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InClusterKataClient {
    pub initialized: bool,
}

impl InClusterKataClient {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_environment() -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn headers(&self) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::from([(String::from("Authorization"), String::new())]))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn request(&self, mut method: String, mut path: String, mut body: Option<std::collections::BTreeMap<String, String>>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn stdout(&self, mut namespace: String, mut pod_name: String, mut limit: i64) -> Result<(Vec<u8>, bool), &'static str> {
        let path: String = format!("/api/v1/namespaces/{}/pods/{}/log?container=scanner", namespace.clone(), pod_name.clone());
        Ok((Vec::new(), false))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn aclose(&self) {
        if !self.initialized {
            return;
        }
    }
}

