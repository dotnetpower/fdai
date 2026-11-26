use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConsoleUpdateTarget {
    pub environment: String,
    pub subscription_id: String,
    pub tenant_id: String,
    pub console_static_web_app_id: String,
    pub console_hostname: String,
    pub operator_api_base_url: String,
    pub ingestion_api_base_url: String,
    pub entra_console_spa_client_id: String,
    pub entra_console_api_scope: String,
    pub release_version: String,
    pub stencil_feature_flags: BTreeMap<String, String>,
}

pub const GUID: &str = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
pub const HOSTNAME: &str = "[a-z0-9-]+(?:[.][0-9]+)?[.]azurestaticapps[.]net";
impl ConsoleUpdateTarget {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_mapping(mut value: std::collections::BTreeMap<String, String>) -> Result<ConsoleUpdateTarget, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn py_validate(&self) -> Result<(), &'static str> {
        if (self.environment.clone()) != (String::from("dev")) {
            return Err("existing Console source updates are supported only in dev");
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn target_binding(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.console-update-target.v2")), (String::from("environment"), self.environment.clone()), (String::from("subscription_id"), self.subscription_id.clone()), (String::from("tenant_id"), self.tenant_id.clone()), (String::from("console_static_web_app_id"), self.console_static_web_app_id.clone()), (String::from("console_hostname"), self.console_hostname.clone()), (String::from("operator_api_base_url"), self.operator_api_base_url.clone()), (String::from("ingestion_api_base_url"), self.ingestion_api_base_url.clone()), (String::from("entra_console_spa_client_id"), self.entra_console_spa_client_id.clone()), (String::from("entra_console_api_scope"), self.entra_console_api_scope.clone()), (String::from("release_version"), self.release_version.clone()), (String::from("stencil_feature_flags"), String::new())])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ConsoleUpdateTarget"];
