#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureEmbeddingConfig {
    pub endpoint: String,
    pub deployment: String,
    pub api_version: String,
    pub dimension: i64,
}

pub const COGNITIVE_SCOPE: &str = "https://cognitiveservices.azure.com/.default";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureEmbeddingModel {
    pub initialized: bool,
}

impl AzureEmbeddingModel {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn readiness(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn probe_readiness(&self) -> String {
        let adapter: String = String::from("azure-openai-embedding");
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn embed(&self, mut text: String) -> Result<Vec<f64>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

