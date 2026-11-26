pub const MAX_ARTIFACT_BYTES: i64 = 1048576;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct KeyVaultResolvedModelsConfig {
    pub vault_url: String,
    pub secret_name: String,
    pub secret_version: Option<String>,
    pub timeout_seconds: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResolvedModelsArtifact {
    pub content: String,
    pub digest: String,
    pub secret_version: Option<String>,
}

pub const KEY_VAULT_AUDIENCE: &str = "https://vault.azure.net/.default";
pub const API_VERSION: &str = "7.4";
pub const SECRET_NAME: &str = "^[A-Za-z0-9-]{1,127}$";
pub const SECRET_VERSION: &str = "^[A-Za-z0-9]{1,64}$";
pub trait AsyncHttpClient {
    fn get(&self, url: String, kwargs: std::collections::BTreeMap<String, String>) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct KeyVaultResolvedModelsSource {
    pub initialized: bool,
}

impl KeyVaultResolvedModelsSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn load(&self) -> Result<ResolvedModelsArtifact, &'static str> {
        Ok(self.load_within_deadline().await.unwrap_or_else(|_| Default::default()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn load_within_deadline(&self) -> Result<ResolvedModelsArtifact, &'static str> {
        let _ = self.validate_attributes(String::new()).unwrap_or_else(|_| ());
        let secret_version: Option<String> = self.response_version(String::new()).unwrap_or_else(|_| None);
        Ok(ResolvedModelsArtifact { secret_version: secret_version.clone(), ..Default::default() })
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn secret_url(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn audience(&self) -> Result<String, &'static str> {
        Err("validated Key Vault URL has one supported DNS suffix")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn validate_attributes(&self, mut raw: String) -> Result<(), &'static str> {
        if false {
            return Ok(());
        }
        if !(false) {
            return Err("Key Vault resolved-model attributes are invalid");
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn response_version(&self, mut raw: String) -> Result<Option<String>, &'static str> {
        if false {
            return Ok(None);
        }
        if !(true) {
            return Err("Key Vault resolved-model secret id is invalid");
        }
        Ok(None)
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["KEY_VAULT_AUDIENCE", "KeyVaultResolvedModelsConfig", "KeyVaultResolvedModelsSource", "ResolvedModelsArtifact"];
