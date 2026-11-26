#[derive(Clone, Debug, Default, PartialEq)]
pub struct KataScanConfig {
    pub namespace: String,
    pub image: String,
    pub source_pvc: String,
    pub source_mount: String,
    pub cache_pvc: Option<String>,
    pub cache_subpath: String,
    pub network_policy: String,
    pub rules_subpath: Option<String>,
    pub cache_mount: Option<String>,
}

pub const NAME: &str = "^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$";
pub const IMAGE: &str = "^[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}$";
pub const RUNTIME: &str = "kata-vm-isolation";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn subpath(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn build_scanner_job(mut config: KataScanConfig, mut scanner_id: String, mut spec: String, mut executable: String, mut source: String, mut job_name: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let source_subpath: String = subpath(String::new()).unwrap_or_else(|_| String::new());
    let mut mounts: Vec<std::collections::BTreeMap<String, String>> = vec![std::collections::BTreeMap::from([(String::from("name"), String::from("source")), (String::from("mountPath"), String::from("/source")), (String::from("subPath"), source_subpath.clone()), (String::from("readOnly"), String::new())]), std::collections::BTreeMap::from([(String::from("name"), String::from("scratch")), (String::from("mountPath"), String::from("/scratch"))]), std::collections::BTreeMap::from([(String::from("name"), String::from("tmp")), (String::from("mountPath"), String::from("/tmp"))])];
    let mut volumes: Vec<std::collections::BTreeMap<String, String>> = vec![std::collections::BTreeMap::from([(String::from("name"), String::from("source")), (String::from("persistentVolumeClaim"), String::new())]), std::collections::BTreeMap::from([(String::from("name"), String::from("scratch")), (String::from("emptyDir"), String::new())]), std::collections::BTreeMap::from([(String::from("name"), String::from("tmp")), (String::from("emptyDir"), String::new())])];
    let container: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("name"), String::from("scanner")), (String::from("image"), config.image.clone()), (String::from("command"), String::new()), (String::from("args"), String::new()), (String::from("workingDir"), String::from("/scratch")), (String::from("env"), String::new()), (String::from("volumeMounts"), String::new()), (String::from("securityContext"), String::new()), (String::from("resources"), String::new())]);
    let pod_spec: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("runtimeClassName"), String::from(RUNTIME)), (String::from("automountServiceAccountToken"), String::new()), (String::from("restartPolicy"), String::from("Never")), (String::from("hostNetwork"), String::new()), (String::from("hostPID"), String::new()), (String::from("hostIPC"), String::new()), (String::from("containers"), String::new()), (String::from("volumes"), String::new()), (String::from("nodeSelector"), String::new()), (String::from("tolerations"), String::new())]);
    Ok(std::collections::BTreeMap::from([(String::from("apiVersion"), String::from("batch/v1")), (String::from("kind"), String::from("Job")), (String::from("metadata"), String::new()), (String::from("spec"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_scanner_pod(mut expected_job: std::collections::BTreeMap<String, String>, mut pod: std::collections::BTreeMap<String, String>, mut uid: String) -> Result<(), &'static str> {
    if expected_job.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_deny_all_policy(mut policy: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
    let spec: Option<String> = (policy.clone()).get("spec").cloned();
    Ok(())
}

