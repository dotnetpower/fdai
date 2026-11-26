#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureOpenAIEmbeddingModelConfig {
    pub endpoint: String,
    pub deployment: String,
    pub api_version: String,
    pub dim: i64,
    pub embedding_space_id: Option<String>,
    pub embedding_model_version: Option<String>,
    pub timeout_seconds: f64,
    pub api_style: String,
    pub auth_audience: String,
    pub route_kind: String,
    pub binding_id: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureOpenAIEmbeddingModel {
    pub initialized: bool,
}

impl AzureOpenAIEmbeddingModel {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn embed(&self, mut text: String) -> Vec<f64> {
        self.embed_observed(text.clone(), String::new()).await.unwrap_or_else(|_| Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn model_provider_observations(&self, mut maximum_age_seconds: i64) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn embed_observed(&self, mut text: String, mut observation: String) -> Result<Vec<f64>, &'static str> {
        let mut request_body: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("input"), String::new()), (String::from("dimensions"), String::new())]);
        Ok(Vec::new())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureOpenAIEmbeddingModel", "AzureOpenAIEmbeddingModelConfig"];
