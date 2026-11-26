#[derive(Clone, Debug, Default, PartialEq)]
pub struct ContainerAppsJobTemplate {
    pub resource_id: String,
    pub authority: String,
    pub image_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ContainerAppsJobConfig {
    pub endpoint: String,
    pub request_timeout_seconds: f64,
    pub read_attempts: i64,
    pub max_retry_after_seconds: f64,
}

pub const EXECUTION_NAME: &str = "^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$";
pub const API_VERSION: &str = "2024-03-01";
pub const AUDIENCE: &str = "https://management.azure.com/.default";
pub const IMAGE_DIGEST: &str = "^[^@\\s]+@sha256:([0-9a-f]{64})$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RetryableArmError {
    pub message: String,
}

impl RetryableArmError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for RetryableArmError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for RetryableArmError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureContainerAppsJobExecutionBackend {
    pub initialized: bool,
}

impl AzureContainerAppsJobExecutionBackend {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn url(&self, mut resource_id: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn execution(&self, mut r#ref: String) -> Result<String, &'static str> {
        Err("Job execution reference is outside configured targets")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn plan(&self, mut request: String, mut profile: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn submit(&self, mut plan: String) -> Result<String, &'static str> {
        let response: String = self.request(String::from("POST"), format!("{}/start", self.url(String::new())), Some(std::collections::BTreeMap::<String, String>::new())).await.unwrap_or_else(|_| String::new());
        let payload: std::collections::BTreeMap<String, String> = object(response.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let name: Option<String> = (payload.clone()).get("name").cloned();
        let r#ref: String = self.execution(String::new()).unwrap_or_else(|_| String::new());
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn status(&self, mut submission_ref: String) -> Result<String, &'static str> {
        let r#ref: String = self.execution(submission_ref.clone()).unwrap_or_else(|_| String::new());
        let payload: std::collections::BTreeMap<String, String> = object(self.request(String::from("GET"), r#ref.clone(), None).await.unwrap_or_else(|_| String::new())).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let properties: Option<String> = (payload.clone()).get("properties").cloned();
        let _ = check_images(String::new(), String::new()).unwrap_or_else(|_| ());
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn cancel(&self, mut submission_ref: String) -> String {
        let r#ref: String = self.execution(submission_ref.clone()).unwrap_or_else(|_| String::new());
        let before: String = self.status(r#ref.clone()).await.unwrap_or_else(|_| String::new());
        let _ = self.request(String::from("POST"), format!("{}/stop", r#ref.clone()), Some(std::collections::BTreeMap::<String, String>::new())).await.unwrap_or_else(|_| String::new());
        self.status(r#ref.clone()).await.unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn collect_receipt(&self, mut submission_ref: String) -> String {
        self.status(submission_ref.clone()).await.unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn cleanup(&self, mut submission_ref: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn capabilities(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn health(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn verify_template(&self, mut resource_id: String, mut digest: String) -> Result<(), &'static str> {
        let payload: std::collections::BTreeMap<String, String> = object(self.request(String::from("GET"), self.url(resource_id.clone()), None).await.unwrap_or_else(|_| String::new())).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let identity: Option<String> = (payload.clone()).get("id").cloned();
        if (!(true)) || ((((identity.clone()).unwrap_or_default()).to_lowercase()) != (resource_id.to_lowercase())) {
            return Err("Job definition identity does not match the target");
        }
        let properties: Option<String> = (payload.clone()).get("properties").cloned();
        let _ = check_images(String::new(), digest.clone()).unwrap_or_else(|_| ());
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn request(&self, mut method: String, mut url: String, mut body: Option<std::collections::BTreeMap<String, String>>) -> Result<String, &'static str> {
        Err("Job ARM read retry budget exhausted")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn send(&self, mut method: String, mut url: String, mut body: Option<std::collections::BTreeMap<String, String>>) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn check_images(mut definition: String, mut digest: String) -> Result<(), &'static str> {
    let mut images: Vec<String> = Vec::<String>::new();
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn object(mut response: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureContainerAppsJobExecutionBackend", "ContainerAppsJobConfig", "ContainerAppsJobTemplate"];
