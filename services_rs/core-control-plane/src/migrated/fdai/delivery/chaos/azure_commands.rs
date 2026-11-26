pub const RC_TIMEOUT: f64 = 180.0;
pub const ARM_TIMEOUT: f64 = 120.0;
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn run_az(mut cmd: Vec<String>, mut timeout: f64) -> (i64, String, String) {
    (0_i64, String::new(), String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn vm_run_command(mut az: String, mut resource_group: String, mut vm_name: String, mut script: String, mut timeout: f64) -> (i64, String, String) {
    run_az(vec![az.clone(), String::from("vm"), String::from("run-command"), String::from("invoke"), String::from("-g"), resource_group.clone(), String::from("-n"), vm_name.clone(), String::from("--command-id"), String::from("RunShellScript"), String::from("--scripts"), script.clone(), String::from("--query"), String::from("value[0].message"), String::from("-o"), String::from("tsv")], timeout).await
}

