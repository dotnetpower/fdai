pub const VM_SHUTDOWN_SCHEDULE_TYPE: &str = "compute.vm-shutdown-schedule";
pub const VM_SHUTDOWN_TASK_TYPE: &str = "ComputeVmShutdownTask";
pub const TIME: &str = "^(?:[01][0-9]|2[0-3])[0-5][0-9]$";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn project_vm_shutdown_schedule(mut props: std::collections::BTreeMap<String, String>) -> Result<Option<std::collections::BTreeMap<String, String>>, &'static str> {
    let provider_type: Option<String> = (props.clone()).get("providerType").cloned();
    let nested_value: Option<String> = (props.clone()).get("properties").cloned();
    let subscription_id: Option<String> = (props.clone()).get("subscriptionId").cloned();
    Ok(Some(std::collections::BTreeMap::from([(String::from("scheduledShutdownStatus"), String::new()), (String::from("scheduledShutdownTime"), String::new()), (String::from("scheduledShutdownTimeZone"), String::new()), (String::from("scheduledShutdownTimeZoneIana"), String::new()), (String::from("scheduledShutdownTargetName"), String::new()), (String::from("scheduledShutdownTargetResourceGroup"), String::new()), (String::from("scheduledShutdownTargetSubscriptionDigest"), String::new())])))
}

pub const PUBLIC_EXPORTS: &[&str] = &["VM_SHUTDOWN_SCHEDULE_TYPE", "VM_SHUTDOWN_TASK_TYPE", "project_vm_shutdown_schedule"];
