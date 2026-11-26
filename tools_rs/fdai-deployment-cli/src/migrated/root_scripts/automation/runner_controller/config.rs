use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Settings {
    pub repository: String,
    pub name_prefix: String,
    pub subscription_id: String,
    pub resource_group: String,
    pub jobs: BTreeMap<String, String>,
    pub worker_image: String,
    pub controller_url: String,
    pub location: String,
    pub vm_subnet_id: String,
    pub vm_image_id: String,
    pub vm_size: String,
    pub ssh_public_key: String,
    pub storage_url: String,
    pub storage_container: String,
    pub storage_blob: String,
    pub cpu_budgets: BTreeMap<String, i64>,
    pub apply: bool,
    pub interval_seconds: i64,
}

impl Settings {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn load(mut raw: String, mut apply: bool, mut hostname: String) -> Result<Settings, &'static str> {
        if raw.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn policies(mut path: String) -> Result<(std::collections::BTreeMap<String, String>, std::collections::BTreeMap<String, String>), &'static str> {
    let mut labels: std::collections::BTreeMap<String, std::collections::BTreeSet<String>> = std::collections::BTreeMap::<String, std::collections::BTreeSet<String>>::new();
    Ok((std::collections::BTreeMap::new(), std::collections::BTreeMap::new()))
}

