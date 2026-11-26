#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn vmss_cpu_metric_templates() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn vm_and_vmss_host_metric_templates() -> std::collections::BTreeMap<String, String> {
    let vm_type: String = String::from("Microsoft.Compute/virtualMachines");
    let vmss_type: String = String::from("Microsoft.Compute/virtualMachineScaleSets");
    std::collections::BTreeMap::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["vm_and_vmss_host_metric_templates", "vmss_cpu_metric_templates"];
