pub const RC_TIMEOUT: f64 = 180.0;
pub const ARM_TIMEOUT: f64 = 120.0;
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn vm_run_command(mut az: String, mut resource_group: String, mut vm_name: String, mut script: String, mut timeout: f64) -> (i64, String, String) {
    (0_i64, String::new(), String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn az(mut cmd: Vec<String>, mut timeout: f64) -> (i64, String, String) {
    (0_i64, String::new(), String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzCliStateProbe", "AzCosmosFailoverInjector", "AzKeyVaultDenyAccessInjector", "AzLbBackendRemoveInjector", "AzNsgRuleInjector", "AzRedisRebootInjector", "AzServiceBusFirewallInjector", "AzVmLifecycleInjector", "AzVmNetworkDisconnectInjector", "AzVmNetworkLatencyInjector", "AzVmPacketLossInjector", "AzVmStopServiceInjector", "AzVmssLifecycleInjector", "_run"];
