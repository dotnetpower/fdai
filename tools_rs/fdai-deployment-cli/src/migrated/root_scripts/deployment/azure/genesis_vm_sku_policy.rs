#[derive(Clone, Debug, Default, PartialEq)]
pub struct VmRole {
    pub name: String,
    pub vcpus: i64,
    pub min_memory_gib: i64,
    pub max_memory_gib: i64,
    pub series: Vec<String>,
    pub disk_mode: String,
    pub preferred: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VmPolicy {
    pub builder: Box<VmRole>,
    pub verifier: Box<VmRole>,
    pub foundation: Box<VmRole>,
    pub os_disk_gib: i64,
    pub digest: String,
}

pub const POLICY_INVALID: &str = "deployment_vm_sku_policy_invalid";
pub const PREFERENCE: &str = "Standard_[A-Za-z0-9_]{1,64}";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn parse_vm_policy(mut raw: Vec<u8>) -> Result<VmPolicy, &'static str> {
    let mut roles: std::collections::BTreeMap<String, VmRole> = std::collections::BTreeMap::<String, VmRole>::new();
    Ok(VmPolicy::default())
}

