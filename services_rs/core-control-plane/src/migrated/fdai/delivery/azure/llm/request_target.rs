use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelRequest {
    pub url: String,
    pub params: BTreeMap<String, String>,
    pub model_body_field: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelRequestTarget {
    pub endpoint: String,
    pub deployment: String,
    pub api_style: String,
    pub api_version: Option<String>,
    pub auth_audience: String,
    pub route_kind: String,
    pub binding_id: Option<String>,
    pub model_family: Option<String>,
}

impl ModelRequestTarget {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.endpoint.trim().is_empty() { return Err("endpoint must be non-empty"); }
        if self.deployment.trim().is_empty() { return Err("deployment must be non-empty"); }
        if self.api_style.trim().is_empty() { return Err("api_style must be non-empty"); }
        if self.auth_audience.trim().is_empty() { return Err("auth_audience must be non-empty"); }
        if self.route_kind.trim().is_empty() { return Err("route_kind must be non-empty"); }
        Ok(())
    }
}

pub const COGNITIVE_SERVICES_SCOPE: &str = "https://cognitiveservices.azure.com/.default";
impl ModelRequestTarget {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn operation(&self, mut operation: String) -> Result<ModelRequest, &'static str> {
        if !(matches!(operation.as_str(), "chat/completions" | "embeddings")) {
            return Err("model operation is unsupported");
        }
        Ok(ModelRequest { model_body_field: Some(self.deployment.clone()), ..Default::default() })
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["COGNITIVE_SERVICES_SCOPE", "ModelRequest", "ModelRequestTarget"];
