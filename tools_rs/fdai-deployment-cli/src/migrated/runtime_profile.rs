#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RuntimePlatform {
    #[default]
    ContainerApps,
    Aks,
}

impl RuntimePlatform {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ContainerApps => "container-apps",
            Self::Aks => "aks",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DatabasePlacement {
    #[default]
    PostgresFlex,
    PostgresAks,
}

impl DatabasePlacement {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::PostgresFlex => "postgres-flex",
            Self::PostgresAks => "postgres-aks",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuntimeDeploymentProfile {
    pub runtime_platform: RuntimePlatform,
    pub database_placement: DatabasePlacement,
    pub system_node_count: i64,
    pub system_node_sku: String,
    pub user_node_min_count: i64,
    pub user_node_max_count: i64,
    pub user_node_sku: String,
    pub product_profile: String,
    pub database_sku: Option<String>,
}

impl RuntimeDeploymentProfile {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn console_selected(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub fn create(mut runtime_platform: String, mut database_placement: String, mut system_node_count: i64, mut system_node_sku: Option<String>, mut user_node_min_count: i64, mut user_node_max_count: i64, mut user_node_sku: String, mut product_add_ons: Vec<String>, mut observation_data_sources: Vec<String>, mut database_sku: Option<String>) -> Result<RuntimeDeploymentProfile, &'static str> {
        if runtime_platform.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_prepare_arguments(mut args: String) -> RuntimeDeploymentProfile {
        if args.is_empty() {
            return Default::default();
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_cli_arguments(mut args: String) -> RuntimeDeploymentProfile {
        if args.is_empty() {
            return Default::default();
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        let mut mapping: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.runtime-deployment-profile.v2")), (String::from("runtime_platform"), String::new()), (String::from("database_placement"), String::new()), (String::from("system_node_count"), String::new()), (String::from("system_node_sku"), self.system_node_sku.clone()), (String::from("user_node_min_count"), String::new()), (String::from("user_node_max_count"), String::new()), (String::from("user_node_sku"), self.user_node_sku.clone()), (String::from("product_profile"), String::new())]);
        if self.database_sku.is_some() {
            mapping.insert(String::from("database_sku"), (self.database_sku.clone()).unwrap_or_default());
        }
        mapping.clone()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_mapping(mut value: std::collections::BTreeMap<String, String>) -> Result<RuntimeDeploymentProfile, &'static str> {
        let schema_version: Option<String> = (value.clone()).get("schema_version").cloned();
        if !(matches!(((schema_version.clone()).unwrap_or_default()).as_str(), "fdai.runtime-deployment-profile.v1" | "fdai.runtime-deployment-profile.v2")) {
            return Err("runtime deployment profile schema is unsupported");
        }
        let product: Option<String> = (value.clone()).get("product_profile").cloned();
        if (schema_version.clone()) == Some(String::from("fdai.runtime-deployment-profile.v1")) {
        } else {
            if !(true) {
                return Err("runtime deployment product profile is missing");
            }
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn matches_mapping(&self, mut value: std::collections::BTreeMap<String, String>) -> bool {
        if value.is_empty() {
            return false;
        }
        false
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn legacy_runtime_profile_mapping(mut profile: RuntimeDeploymentProfile) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn legacy_runtime_profile_digest(mut profile: RuntimeDeploymentProfile) -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn legacy_full_product_matches(mut profile: RuntimeDeploymentProfile, mut retained_digest: String) -> bool {
    let selected: String = profile.product_profile.clone();
    false
}

