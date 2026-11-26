//! Pure zero-I/O Azure IAM 3-tier permission group validator.
//! Enforces mandatory NotActions/NotDataActions, Thor-only write rule,
//! human-vs-workload group separation, no-PIM baseline, subscription-default scope,
//! and fail-closed startup role readback.
#![deny(clippy::all)]

use fdai_contracts::azure_iam_groups::{AzureIamCatalog, AzureIamProfileSelection};
use std::collections::BTreeSet;

const REQUIRED_GROUPS: [&str; 3] = ["reader", "operator", "contributor"];
const MANDATORY_NOT_ACTIONS: [&str; 9] = [
    "Microsoft.Authorization/*/Write",
    "Microsoft.Authorization/*/Delete",
    "Microsoft.Authorization/elevateAccess/Action",
    "Microsoft.Resources/subscriptions/resourceGroups/delete",
    "Microsoft.Authorization/locks/delete",
    "Microsoft.Subscription/*",
    "*/listKeys/action",
    "*/listSecrets/action",
    "Microsoft.KeyVault/vaults/purge/action",
];
const MANDATORY_NOT_DATA_ACTIONS: [&str; 1] = [
    "Microsoft.KeyVault/vaults/secrets/getSecret/action",
];
const PANTHEON_AGENTS: [&str; 15] = [
    "Odin",
    "Thor",
    "Forseti",
    "Huginn",
    "Heimdall",
    "Vidar",
    "Var",
    "Bragi",
    "Saga",
    "Mimir",
    "Muninn",
    "Norns",
    "Njord",
    "Freyr",
    "Loki",
];

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureIamCatalogReport {
    pub catalog_id: String,
    pub group_count: usize,
    pub pim_required: bool,
    pub default_custom_role_scope: String,
    pub warnings: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RoleReadbackDecision {
    pub allowed: bool,
    pub overbroad_roles: Vec<String>,
    pub reason: String,
}

pub fn validate_azure_iam_catalog(
    catalog: &AzureIamCatalog,
) -> Result<AzureIamCatalogReport, Vec<String>> {
    let mut errors = Vec::new();
    let warnings = Vec::new();

    if catalog.schema_version.trim().is_empty() || catalog.catalog_id.trim().is_empty() {
        errors.push(String::from("schema_version and catalog_id must be non-empty"));
    }

    if catalog.defaults.custom_role_scope != "subscription" {
        errors.push(format!(
            "default custom_role_scope must be 'subscription', found '{}'",
            catalog.defaults.custom_role_scope
        ));
    }
    if catalog.defaults.pim_required {
        errors.push(String::from("defaults.pim_required must be false (no-PIM baseline)"));
    }
    if catalog.defaults.binding_mode != "direct" {
        errors.push(format!(
            "default binding_mode must be 'direct', found '{}'",
            catalog.defaults.binding_mode
        ));
    }
    if catalog.defaults.default_workload_group != "reader" {
        errors.push(String::from("default_workload_group must be 'reader'"));
    }
    if !matches!(
        catalog.defaults.dev_gateway_executor_group.as_str(),
        "operator" | "contributor"
    ) {
        errors.push(String::from(
            "dev_gateway_executor_group must be 'operator' or 'contributor'",
        ));
    }

    if catalog.groups.len() != REQUIRED_GROUPS.len() {
        errors.push(format!(
            "expected exactly {} permission groups, found {}",
            REQUIRED_GROUPS.len(),
            catalog.groups.len()
        ));
    }

    let mut seen_ids = BTreeSet::new();
    let mut mi_groups = BTreeSet::new();
    let mut covered_agents = BTreeSet::new();

    for group in &catalog.groups {
        if !seen_ids.insert(group.id.as_str()) {
            errors.push(format!("duplicate group id '{}'", group.id));
        }
        if group.pim_required {
            errors.push(format!("group '{}' must not require PIM by default", group.id));
        }
        for req_na in MANDATORY_NOT_ACTIONS {
            if !group.not_actions.iter().any(|na| na == req_na) {
                errors.push(format!(
                    "group '{}' missing mandatory NotAction '{}'",
                    group.id, req_na
                ));
            }
        }
        for req_nda in MANDATORY_NOT_DATA_ACTIONS {
            if !group.not_data_actions.iter().any(|nda| nda == req_nda) {
                errors.push(format!(
                    "group '{}' missing mandatory NotDataAction '{}'",
                    group.id, req_nda
                ));
            }
        }

        if group.id == "reader" && group.allows_write {
            errors.push(String::from("reader group must not allow write operations"));
        }
        if group.id == "contributor" {
            if !group.single_dedicated_rg_only {
                errors.push(String::from(
                    "contributor group must set single_dedicated_rg_only = true",
                ));
            }
            if group.default_production_eligible {
                errors.push(String::from(
                    "contributor group must not be default_production_eligible",
                ));
            }
            if group.allowed_scopes.iter().any(|s| s == "subscription") {
                errors.push(String::from(
                    "contributor group must not allow subscription scope",
                ));
            }
        }
        if group.allows_write {
            if group.allowed_scopes.iter().any(|s| s == "subscription") {
                errors.push(format!(
                    "write group '{}' must be RG-scoped, not subscription-wide",
                    group.id
                ));
            }
            for agent in &group.assigned_agents {
                if agent != "Thor" {
                    errors.push(format!(
                        "only Thor may hold write group '{}', found '{}'",
                        group.id, agent
                    ));
                }
            }
        }

        for agent in &group.assigned_agents {
            covered_agents.insert(agent.as_str());
        }
        for mg in &group.entra_mi_groups {
            if !mg.starts_with("fdai-mi-") {
                errors.push(format!(
                    "workload Entra group '{}' must use 'fdai-mi-' prefix",
                    mg
                ));
            }
            mi_groups.insert(mg.as_str());
        }
    }

    for required in REQUIRED_GROUPS {
        if !seen_ids.contains(required) {
            errors.push(format!("missing required permission group '{required}'"));
        }
    }

    for agent in &catalog.no_target_azure_role_agents {
        covered_agents.insert(agent.as_str());
    }
    for pantheon_agent in PANTHEON_AGENTS {
        if !covered_agents.contains(pantheon_agent) {
            errors.push(format!(
                "Pantheon agent '{pantheon_agent}' is not mapped in catalog"
            ));
        }
    }

    let mut human_groups = BTreeSet::new();
    for human in &catalog.human_admin_groups {
        if human.pim_required {
            errors.push(format!(
                "human admin role '{}' must not require PIM by default",
                human.role
            ));
        }
        if !human.entra_group.starts_with("fdai-") || human.entra_group.starts_with("fdai-mi-") {
            errors.push(format!(
                "human Entra group '{}' must use 'fdai-' prefix and never 'fdai-mi-'",
                human.entra_group
            ));
        }
        if mi_groups.contains(human.entra_group.as_str()) {
            errors.push(format!(
                "human group '{}' overlaps with workload MI group",
                human.entra_group
            ));
        }
        if human.role == "BreakGlass" && human.hil_approval_allowed {
            errors.push(String::from("BreakGlass must never allow HIL approval"));
        }
        human_groups.insert(human.entra_group.as_str());
    }

    if human_groups.len() < 5 {
        errors.push(String::from(
            "human_admin_groups must declare all 5 roles (Reader, Contributor, Approver, Owner, BreakGlass)",
        ));
    }

    if !errors.is_empty() {
        return Err(errors);
    }

    Ok(AzureIamCatalogReport {
        catalog_id: catalog.catalog_id.clone(),
        group_count: catalog.groups.len(),
        pim_required: catalog.defaults.pim_required,
        default_custom_role_scope: catalog.defaults.custom_role_scope.clone(),
        warnings,
    })
}

pub fn validate_profile_selection(
    catalog: &AzureIamCatalog,
    selection: &AzureIamProfileSelection,
    target_environment: &str,
) -> Result<(), String> {
    let Some(group) = catalog
        .groups
        .iter()
        .find(|g| g.id == selection.workload_group)
    else {
        return Err(format!(
            "unknown workload_group '{}': expected reader, operator, or contributor",
            selection.workload_group
        ));
    };

    if !catalog
        .defaults
        .allowed_binding_modes
        .iter()
        .any(|m| m == &selection.binding_mode)
    {
        return Err(format!(
            "unsupported binding_mode '{}': expected direct or entra_group",
            selection.binding_mode
        ));
    }

    if !catalog
        .defaults
        .allowed_custom_role_scopes
        .iter()
        .any(|s| s == &selection.custom_role_scope)
    {
        return Err(format!(
            "unsupported custom_role_scope '{}': expected subscription or management_group",
            selection.custom_role_scope
        ));
    }

    if !matches!(
        selection.dev_gateway_executor_group.as_str(),
        "operator" | "contributor"
    ) {
        return Err(format!(
            "unsupported dev_gateway_executor_group '{}': expected operator or contributor",
            selection.dev_gateway_executor_group
        ));
    }

    if target_environment.eq_ignore_ascii_case("production") && !group.default_production_eligible {
        return Err(format!(
            "group '{}' is not eligible for default production workloads (dedicated dev/test RG only)",
            group.id
        ));
    }

    Ok(())
}

#[must_use]
pub fn evaluate_standing_role_readback(
    catalog: &AzureIamCatalog,
    observed_role_names: &[&str],
) -> RoleReadbackDecision {
    let mut overbroad = Vec::new();
    for observed in observed_role_names {
        if catalog
            .safety_floor
            .forbidden_standing_roles
            .iter()
            .any(|banned| banned.eq_ignore_ascii_case(observed.trim()))
        {
            overbroad.push((*observed).to_string());
        }
    }

    if overbroad.is_empty() {
        RoleReadbackDecision {
            allowed: true,
            overbroad_roles: Vec::new(),
            reason: String::from("effective standing roles satisfy FDAI safety floor"),
        }
    } else {
        RoleReadbackDecision {
            allowed: false,
            overbroad_roles: overbroad,
            reason: String::from("fail-closed: over-broad standing Azure role detected"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use fdai_contracts::azure_iam_groups::load_embedded_azure_iam_catalog;

    #[test]
    fn embedded_catalog_passes_all_invariants() {
        let catalog = load_embedded_azure_iam_catalog();
        assert!(catalog.is_ok());
        if let Ok(cat) = catalog {
            let report = validate_azure_iam_catalog(&cat);
            assert!(report.is_ok(), "unexpected errors: {report:?}");
            if let Ok(rep) = report {
                assert_eq!(rep.group_count, 3);
                assert!(!rep.pim_required);
                assert_eq!(rep.default_custom_role_scope, "subscription");
            }
        }
    }

    #[test]
    fn rejects_non_thor_write_agent_and_contributor_in_production() {
        let Ok(mut cat) = load_embedded_azure_iam_catalog() else {
            return;
        };
        if let Some(op) = cat.groups.iter_mut().find(|g| g.id == "operator") {
            op.assigned_agents.push(String::from("Forseti"));
        }
        let err = validate_azure_iam_catalog(&cat);
        assert!(err.is_err());

        let Ok(clean) = load_embedded_azure_iam_catalog() else {
            return;
        };
        let prod_contrib = AzureIamProfileSelection {
            workload_group: String::from("contributor"),
            binding_mode: String::from("direct"),
            custom_role_scope: String::from("subscription"),
            dev_gateway_executor_group: String::from("operator"),
            pim_required: false,
        };
        assert!(validate_profile_selection(&clean, &prod_contrib, "production").is_err());
        assert!(validate_profile_selection(&clean, &prod_contrib, "dev").is_ok());
    }

    #[test]
    fn readback_fails_closed_on_overbroad_standing_roles() {
        let Ok(cat) = load_embedded_azure_iam_catalog() else {
            return;
        };
        let ok = evaluate_standing_role_readback(&cat, &["FDAI Reader v1", "FDAI Operator v1"]);
        assert!(ok.allowed);

        let blocked = evaluate_standing_role_readback(&cat, &["FDAI Operator v1", "Owner"]);
        assert!(!blocked.allowed);
        assert_eq!(blocked.overbroad_roles, vec![String::from("Owner")]);
    }
}
