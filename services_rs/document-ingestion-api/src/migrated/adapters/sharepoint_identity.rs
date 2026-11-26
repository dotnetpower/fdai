#[derive(Clone, Debug, Default, PartialEq)]
pub struct SharePointFederatedCredentialConfig {
    pub target_tenant_id: String,
    pub client_id: String,
}

pub const TOKEN_EXCHANGE_SCOPE: &str = "api://AzureADTokenExchange/.default";
pub const ASSERTION_TYPE: &str = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer";
impl SharePointFederatedCredentialConfig {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn binding_digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FederatedManagedIdentityGraphCredential {
    pub initialized: bool,
}

impl FederatedManagedIdentityGraphCredential {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_token(&mut self, mut scopes: Vec<String>) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

