//! Azure IAM Permission Groups contract (`config/azure-iam-permission-groups.json`).
//! Pure serde data contracts and canonical digest helper (zero runtime I/O).
#![deny(clippy::all)]

use serde::{Deserialize, Serialize};

pub const EMBEDDED_AZURE_IAM_CATALOG_JSON: &str =
    include_str!("../../../../config/azure-iam-permission-groups.json");

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct AzureIamCatalog {
    pub schema_version: String,
    pub catalog_id: String,
    pub defaults: AzureIamDefaults,
    pub safety_floor: AzureIamSafetyFloor,
    pub groups: Vec<AzureIamPermissionGroup>,
    pub no_target_azure_role_agents: Vec<String>,
    pub human_admin_groups: Vec<HumanAdminGroup>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct AzureIamDefaults {
    pub custom_role_scope: String,
    pub allowed_custom_role_scopes: Vec<String>,
    pub pim_required: bool,
    pub binding_mode: String,
    pub allowed_binding_modes: Vec<String>,
    pub default_workload_group: String,
    pub dev_gateway_executor_group: String,
    pub dev_gateway_replaces_builtin_roles: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct AzureIamSafetyFloor {
    pub not_actions: Vec<String>,
    pub not_data_actions: Vec<String>,
    pub forbidden_standing_roles: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct AzureIamPermissionGroup {
    pub id: String,
    pub display_name: String,
    pub role_name_template: String,
    pub version: String,
    pub allows_write: bool,
    pub single_dedicated_rg_only: bool,
    pub default_production_eligible: bool,
    pub pim_required: bool,
    pub allowed_scopes: Vec<String>,
    pub summary_en: String,
    pub summary_ko: String,
    pub actions: Vec<String>,
    pub not_actions: Vec<String>,
    pub data_actions: Vec<String>,
    pub not_data_actions: Vec<String>,
    pub assigned_agents: Vec<String>,
    pub non_pantheon_principals: Vec<String>,
    pub entra_mi_groups: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct HumanAdminGroup {
    pub role: String,
    pub label_ko: String,
    pub entra_group: String,
    pub legacy_entra_group: String,
    pub azure_iam_recommendation: String,
    pub azure_iam_label_ko: String,
    pub pim_required: bool,
    pub hil_approval_allowed: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct AzureIamProfileSelection {
    pub workload_group: String,
    pub binding_mode: String,
    pub custom_role_scope: String,
    pub dev_gateway_executor_group: String,
    pub pim_required: bool,
}

pub fn parse_azure_iam_catalog_json(raw_json: &str) -> Result<AzureIamCatalog, String> {
    serde_json::from_str::<AzureIamCatalog>(raw_json)
        .map_err(|err| format!("invalid azure iam permission groups json: {err}"))
}

#[must_use]
pub fn azure_iam_catalog_digest_hex(raw_json: &str) -> String {
    format!("{:016x}", crate::canonical_digest_fnv1a64(raw_json.as_bytes()))
}

pub fn load_embedded_azure_iam_catalog() -> Result<AzureIamCatalog, String> {
    parse_azure_iam_catalog_json(EMBEDDED_AZURE_IAM_CATALOG_JSON)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_embedded_catalog_and_recommended_defaults() {
        let catalog = load_embedded_azure_iam_catalog();
        assert!(catalog.is_ok());
        if let Ok(cat) = catalog {
            assert_eq!(cat.groups.len(), 3);
            assert_eq!(cat.defaults.custom_role_scope, "subscription");
            assert!(!cat.defaults.pim_required);
            assert_eq!(cat.defaults.binding_mode, "direct");
            assert_eq!(cat.defaults.dev_gateway_executor_group, "operator");
            assert_eq!(cat.human_admin_groups.len(), 5);
            assert_eq!(cat.no_target_azure_role_agents.len(), 12);
        }
        let digest = azure_iam_catalog_digest_hex(EMBEDDED_AZURE_IAM_CATALOG_JSON);
        assert_eq!(digest.len(), 16);
    }
}
