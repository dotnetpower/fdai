#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ApprovalClass {
    #[default]
    Standard,
    HighImpact,
}

impl ApprovalClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Standard => "standard",
            Self::HighImpact => "high-impact",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProvisionProfile {
    pub environment: String,
    pub region: String,
    pub target_binding: String,
    pub connectivity: String,
    pub host: String,
    pub transport: String,
    pub access_method: String,
    pub shadow_only: bool,
    pub approval_quorum: i64,
    pub monthly_cost_ceiling: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ManifestEntry {
    pub entry_id: String,
    pub owner: String,
    pub desired_state: String,
    pub prerequisites: Vec<String>,
    pub approval_class: ApprovalClass,
    pub idempotency_key: String,
    pub timeout_seconds: i64,
    pub no_progress_seconds: i64,
    pub rollback_ref: String,
    pub observer: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SubscriptionProvisioningManifest {
    pub source_commit: String,
    pub profile_digest: String,
    pub entries: Vec<ManifestEntry>,
}

pub const ID: &str = "^[a-z][a-z0-9._-]{0,127}$";
pub const ENVIRONMENTS: &[&str] = &["dev", "staging", "prod"];
pub const CONNECTIVITY: &[&str] = &["online", "offline"];
pub const HOSTS: &[&str] = &["existing-host", "managed-vm"];
pub const TRANSPORTS: &[&str] = &["manual"];
pub const ACCESS_METHODS: &[&str] = &["internal_ssh", "temporary_public_ssh", "bastion", "run_command"];
impl ProvisionProfile {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_mapping(mut value: std::collections::BTreeMap<String, String>) -> Result<ProvisionProfile, &'static str> {
        let expected: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("schema_version"), String::from("environment"), String::from("region"), String::from("target_binding"), String::from("connectivity"), String::from("host"), String::from("transport"), String::from("access_method"), String::from("shadow_only"), String::from("approval_quorum"), String::from("monthly_cost_ceiling")]);
        let _ = require_exact_keys(value.clone(), expected.clone(), String::from("provision profile")).unwrap_or_else(|_| ());
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.provision-profile.v1")), (String::from("environment"), self.environment.clone()), (String::from("region"), self.region.clone()), (String::from("target_binding"), self.target_binding.clone()), (String::from("connectivity"), self.connectivity.clone()), (String::from("host"), self.host.clone()), (String::from("transport"), self.transport.clone()), (String::from("access_method"), self.access_method.clone()), (String::from("shadow_only"), String::new()), (String::from("approval_quorum"), String::new()), (String::from("monthly_cost_ceiling"), String::new())])
    }
}

impl ManifestEntry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("entry_id"), self.entry_id.clone()), (String::from("owner"), self.owner.clone()), (String::from("desired_state"), self.desired_state.clone()), (String::from("prerequisites"), String::new()), (String::from("approval_class"), String::new()), (String::from("idempotency_key"), self.idempotency_key.clone()), (String::from("timeout_seconds"), String::new()), (String::from("no_progress_seconds"), String::new()), (String::from("rollback_ref"), self.rollback_ref.clone()), (String::from("observer"), self.observer.clone())])
    }
}

impl SubscriptionProvisioningManifest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.subscription-provisioning-manifest.v1")), (String::from("source_commit"), self.source_commit.clone()), (String::from("profile_digest"), self.profile_digest.clone()), (String::from("entries"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn assert_acyclic(mut entries: Vec<ManifestEntry>) -> Result<(), &'static str> {
    let visiting: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let visited: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_exact_keys(mut value: std::collections::BTreeMap<String, String>, mut expected: std::collections::BTreeSet<String>, mut label: String) -> Result<(), &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut value: std::collections::BTreeMap<String, String>, mut field: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bool(mut value: std::collections::BTreeMap<String, String>, mut field: String) -> Result<bool, &'static str> {
    Ok(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn int(mut value: std::collections::BTreeMap<String, String>, mut field: String) -> Result<i64, &'static str> {
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_json_object(mut data: Vec<u8>, mut label: String, mut max_bytes: i64, mut strict: bool) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if ((data.clone()).is_empty()) || ((((data.clone()).len() as i64)) > (max_bytes)) {
        return Err("label is empty or exceeds its size limit");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn unique_json_object(mut pairs: Vec<(String, String)>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn reject_json_constant(mut value: String) -> Result<String, &'static str> {
    Err("non-finite JSON number")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn finite_json_float(mut value: String) -> Result<f64, &'static str> {
    let number: f64 = (value.clone()).trim().parse::<f64>().unwrap_or(0.0);
    Ok(number)
}

