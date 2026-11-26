#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ModelProviderKind {
    #[default]
    AzureOpenai,
    AzureFoundry,
    SelfHosted,
}

impl ModelProviderKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::AzureOpenai => "azure-openai",
            Self::AzureFoundry => "azure-foundry",
            Self::SelfHosted => "self-hosted",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ModelRouteKind {
    #[default]
    Direct,
    ApimGateway,
}

impl ModelRouteKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Direct => "direct",
            Self::ApimGateway => "apim-gateway",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ModelApiStyle {
    #[default]
    AzureOpenai,
    OpenaiV1,
}

impl ModelApiStyle {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::AzureOpenai => "azure-openai",
            Self::OpenaiV1 => "openai-v1",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ModelAuthKind {
    #[default]
    Entra,
    ApiKeyRef,
    None,
}

impl ModelAuthKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Entra => "entra",
            Self::ApiKeyRef => "api-key-ref",
            Self::None => "none",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ModelCapacityUnit {
    #[default]
    Tpm,
    Ptu,
    Gpu,
}

impl ModelCapacityUnit {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Tpm => "tpm",
            Self::Ptu => "ptu",
            Self::Gpu => "gpu",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ModelDiscoverySource {
    #[default]
    AzureManagement,
    ApimManagement,
    SignedRegistration,
    StaticConfig,
}

impl ModelDiscoverySource {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::AzureManagement => "azure-management",
            Self::ApimManagement => "apim-management",
            Self::SignedRegistration => "signed-registration",
            Self::StaticConfig => "static-config",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelEndpointFeatures {
    pub streaming: bool,
    pub embeddings: bool,
    pub structured_output: bool,
    pub tool_calling: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelEndpointCapacity {
    pub unit: ModelCapacityUnit,
    pub value: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelEndpointDiscovery {
    pub source: ModelDiscoverySource,
    pub resource_ref_digest: String,
    pub verified_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelEndpointBinding {
    pub binding_id: String,
    pub capability: String,
    pub provider_kind: ModelProviderKind,
    pub route_kind: ModelRouteKind,
    pub api_style: ModelApiStyle,
    pub endpoint_ref: String,
    pub deployment: String,
    pub auth_kind: ModelAuthKind,
    pub auth_audience: Option<String>,
    pub publisher: String,
    pub family: String,
    pub version: Option<String>,
    pub capacity: Box<ModelEndpointCapacity>,
    pub features: Box<ModelEndpointFeatures>,
    pub discovery: Box<ModelEndpointDiscovery>,
    pub api_version: Option<String>,
}

impl ModelEndpointBinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.binding_id.trim().is_empty() { return Err("binding_id must be non-empty"); }
        if self.capability.trim().is_empty() { return Err("capability must be non-empty"); }
        if self.endpoint_ref.trim().is_empty() { return Err("endpoint_ref must be non-empty"); }
        if self.deployment.trim().is_empty() { return Err("deployment must be non-empty"); }
        if self.publisher.trim().is_empty() { return Err("publisher must be non-empty"); }
        if self.family.trim().is_empty() { return Err("family must be non-empty"); }
        Ok(())
    }
}

pub const IDENTIFIER: &str = "^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$";
pub const REFERENCE: &str = "^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,1023}$";
pub const DIGEST: &str = "^[a-f0-9]{64}$";
impl ModelEndpointBinding {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("binding_id"), self.binding_id.clone()), (String::from("capability"), self.capability.clone()), (String::from("provider_kind"), String::new()), (String::from("route_kind"), String::new()), (String::from("api_style"), String::new()), (String::from("endpoint_ref"), self.endpoint_ref.clone()), (String::from("deployment"), self.deployment.clone()), (String::from("api_version"), (self.api_version.clone()).unwrap_or_default()), (String::from("auth"), String::new()), (String::from("model"), String::new()), (String::from("capacity"), String::new()), (String::from("features"), String::new()), (String::from("discovery"), String::new())])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_dict(mut raw: std::collections::BTreeMap<String, String>) -> ModelEndpointBinding {
        let auth: std::collections::BTreeMap<String, String> = mapping(raw.clone(), String::from("auth")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let model: std::collections::BTreeMap<String, String> = mapping(raw.clone(), String::from("model")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let capacity: std::collections::BTreeMap<String, String> = mapping(raw.clone(), String::from("capacity")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let features: std::collections::BTreeMap<String, String> = mapping(raw.clone(), String::from("features")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let discovery: std::collections::BTreeMap<String, String> = mapping(raw.clone(), String::from("discovery")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        Default::default()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn mapping(mut raw: std::collections::BTreeMap<String, String>, mut key: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let value: Option<String> = (raw.clone()).get(key.as_str()).cloned();
    if !(true) {
        return Err("model endpoint key MUST be an object");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn optional_string(mut value: String) -> Option<String> {
    if true { Some(value.clone()) } else { None }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_identifier(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_reference(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ModelApiStyle", "ModelAuthKind", "ModelCapacityUnit", "ModelDiscoverySource", "ModelEndpointBinding", "ModelEndpointCapacity", "ModelEndpointDiscovery", "ModelEndpointFeatures", "ModelProviderKind", "ModelRouteKind"];
