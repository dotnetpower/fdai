#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScanWorkerInstallConfig {
    pub controller_namespace: String,
    pub controller_service_account: String,
    pub scanner_namespace: String,
    pub image: String,
    pub controller_source_pvc: String,
    pub scanner_source_pvc: String,
    pub controller_cache_pvc: String,
    pub scanner_cache_pvc: String,
    pub cache_subpath: String,
    pub state_secret: String,
    pub broker_config_map: String,
    pub request_schedule: String,
    pub scan_schedule: String,
    pub max_batch: i64,
    pub github_app_secret: Option<String>,
    pub enabled: bool,
}

pub const NAME: &str = "^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn secret_environment(mut name: String, mut secret: String, mut key: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("name"), name.clone()), (String::from("valueFrom"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn cronjob(mut config: ScanWorkerInstallConfig, mut requests: bool) -> std::collections::BTreeMap<String, String> {
    let suffix: String = if requests { String::from("requests") } else { String::from("schedule") };
    let command: String = if requests { String::from("process-scan-requests") } else { String::from("process-scheduled-scans") };
    let mut args: Vec<String> = vec![command.clone(), String::from("--state-access"), String::from("restricted"), String::from("--scanner-runtime"), String::from("kata"), String::from("--scanner-namespace"), config.scanner_namespace.clone(), String::from("--scanner-image"), config.image.clone(), String::from("--scanner-source-pvc"), config.scanner_source_pvc.clone(), String::from("--scanner-source-mount"), String::from("/work"), String::from("--scanner-cache-pvc"), config.scanner_cache_pvc.clone(), String::from("--scanner-cache-subpath"), config.cache_subpath.clone(), String::from("--cache-dir"), String::from("/cache"), String::from("--work-root"), String::from("/work/controller"), String::from("--kafka-bootstrap-servers"), String::from("$(FDAI_SCAN_BROKER)"), if requests { String::from("--max-requests") } else { String::from("--max-repositories") }, (config.max_batch).to_string()];
    std::collections::BTreeMap::from([(String::from("apiVersion"), String::from("batch/v1")), (String::from("kind"), String::from("CronJob")), (String::from("metadata"), String::new()), (String::from("spec"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn scan_worker_resources(mut config: ScanWorkerInstallConfig) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let controller: Vec<std::collections::BTreeMap<String, String>> = vec![std::collections::BTreeMap::from([(String::from("apiVersion"), String::from("v1")), (String::from("kind"), String::from("Namespace")), (String::from("metadata"), String::new())]), std::collections::BTreeMap::from([(String::from("apiVersion"), String::from("v1")), (String::from("kind"), String::from("ServiceAccount")), (String::from("metadata"), String::new()), (String::from("automountServiceAccountToken"), String::new())])];
    Ok(std::collections::BTreeMap::from([(String::from("apiVersion"), String::from("v1")), (String::from("kind"), String::from("List")), (String::from("items"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn add_worker_render_command(mut sub: String) {
    if sub.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn render_scanner_workers(mut args: String) -> std::collections::BTreeMap<String, String> {
    let config: ScanWorkerInstallConfig = ScanWorkerInstallConfig::default();
    std::collections::BTreeMap::from([(String::from("ok"), String::new()), (String::from("resources"), String::new())])
}

