pub trait AccessToken {
    fn token(&self) -> String;
}

pub trait Credential {
    fn get_token(&self, scopes: Vec<String>) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct WorkloadIdentityAuthorization {
    pub initialized: bool,
}

impl WorkloadIdentityAuthorization {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn call(&self) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn close(&self) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn credential() -> Result<String, &'static str> {
    let required: String = String::from("AZURE_TENANT_ID\", \"AZURE_CLIENT_ID\", \"AZURE_FEDERATED_TOKEN_FILE");
    Ok(String::new())
}

