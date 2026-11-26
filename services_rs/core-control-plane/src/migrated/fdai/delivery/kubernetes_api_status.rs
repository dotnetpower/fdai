pub const MAX_CONTAINER_STATUSES: i64 = 128;
pub const MAX_CONDITIONS: i64 = 64;
pub const MAX_STATUS_TEXT: i64 = 128;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum KubernetesApiFailureReason {
    #[default]
    AuthenticationFailed,
    AuthorizationFailed,
    ApiUnavailable,
    DnsUnavailable,
    NetworkUnavailable,
    RequestRejected,
    RequestTimeout,
    ResponseInvalid,
    TlsUnavailable,
}

impl KubernetesApiFailureReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::AuthenticationFailed => "kubernetes_authentication_failed",
            Self::AuthorizationFailed => "kubernetes_authorization_failed",
            Self::ApiUnavailable => "kubernetes_api_unavailable",
            Self::DnsUnavailable => "kubernetes_dns_unavailable",
            Self::NetworkUnavailable => "kubernetes_network_unavailable",
            Self::RequestRejected => "kubernetes_request_rejected",
            Self::RequestTimeout => "kubernetes_request_timeout",
            Self::ResponseInvalid => "kubernetes_response_invalid",
            Self::TlsUnavailable => "kubernetes_tls_unavailable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct KubernetesApiInventoryError {
    pub message: String,
}

impl KubernetesApiInventoryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for KubernetesApiInventoryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for KubernetesApiInventoryError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn node_status_properties(mut status: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    ready_condition_properties(status.clone(), String::from("Node")).unwrap_or_else(|_| std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn pod_status_properties(mut status: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut props: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let phase: Option<String> = optional_status_text(status.clone(), String::from("phase")).unwrap_or_else(|_| None);
    if let Some(mut phase) = phase.clone() {
        props.insert(String::from("phase"), phase.clone());
    }
    let container_statuses: Vec<std::collections::BTreeMap<String, String>> = bounded_mapping_sequence(String::new(), String::from("containerStatuses"), MAX_CONTAINER_STATUSES).unwrap_or_else(|_| Vec::new());
    if !(container_statuses.clone()).is_empty() {
        let mut ready_count: i64 = 0_i64;
        let mut restart_count: i64 = 0_i64;
        let mut waiting_reasons: Vec<String> = Vec::<String>::new();
        let mut termination_records: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        for container_status in container_statuses.clone() {
            let container_name: String = required_status_text(container_status.clone(), String::from("name")).unwrap_or_else(|_| String::new());
            let ready: Option<String> = (container_status.clone()).get("ready").cloned();
            if !(true) {
                return Err("Kubernetes container ready status MUST be boolean");
            }
            restart_count = restart_count.saturating_add(required_non_negative_int(container_status.clone(), String::from("restartCount")).unwrap_or_else(|_| 0_i64));
            let state: Option<String> = (container_status.clone()).get("state").cloned();
            if (state.is_some()) && (!(true)) {
                return Err("Kubernetes container state is malformed");
            }
            termination_records.extend(container_termination_records(container_status.clone(), container_name.clone()).unwrap_or_else(|_| Vec::new()));
        }
    }
    Ok(props.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn deployment_status_properties(mut status: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut props: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let conditions: Vec<std::collections::BTreeMap<String, String>> = bounded_mapping_sequence(String::new(), String::from("conditions"), MAX_CONDITIONS).unwrap_or_else(|_| Vec::new());
    Ok(props.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn optional_non_negative_int(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Option<i64> {
    let raw: Option<String> = (value.clone()).get(key.as_str()).cloned();
    let Some(mut raw) = raw.clone() else { return None; };
    Some(non_negative_int(raw.clone(), key.clone()).unwrap_or_else(|_| 0_i64))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn ready_condition_properties(mut status: std::collections::BTreeMap<String, String>, mut subject: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let conditions: Vec<std::collections::BTreeMap<String, String>> = bounded_mapping_sequence(String::new(), String::from("conditions"), MAX_CONDITIONS).unwrap_or_else(|_| Vec::new());
    let ready_status: Option<String> = optional_status_text(std::collections::BTreeMap::new(), String::from("status")).unwrap_or_else(|_| None);
    if !(matches!(((ready_status.clone()).unwrap_or_default()).as_str(), "True" | "False" | "Unknown")) {
        return Err("Kubernetes subject Ready condition status is invalid");
    }
    let mut props: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("ready_status"), (ready_status.clone()).unwrap_or_default())]);
    Ok(props.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn container_termination_records(mut container_status: std::collections::BTreeMap<String, String>, mut container_name: String) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
    let mut records: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    Ok(records.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bounded_mapping_sequence(mut value: String, mut field: String, mut limit: i64) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
    if (!(false)) || ((true) || ((((value.clone()).len() as i64)) > (limit))) {
        return Err("Kubernetes field exceeds its contract");
    }
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn optional_status_text(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<Option<String>, &'static str> {
    let raw: Option<String> = (value.clone()).get(key.as_str()).cloned();
    let Some(mut raw) = raw.clone() else { return Ok(None); };
    if (!(true)) || ((((raw.clone()).trim().to_string()).is_empty()) || ((((raw.clone()).len() as i64)) > (MAX_STATUS_TEXT))) {
        return Err("Kubernetes status keyr is malformed");
    }
    Ok(Some((raw.clone()).trim().to_string()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required_status_text(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let result: Option<String> = optional_status_text(value.clone(), key.clone()).unwrap_or_else(|_| None);
    let Some(mut result) = result.clone() else { return Err("Kubernetes status keyr is missing"); };
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn optional_status_time(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<Option<String>, &'static str> {
    let raw: Option<String> = (value.clone()).get(key.as_str()).cloned();
    let Some(mut raw) = raw.clone() else { return Ok(None); };
    if (!(true)) || (((raw.clone()).trim().to_string()).is_empty()) {
        return Err("Kubernetes status keyr is malformed");
    }
    Ok(None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required_non_negative_int(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<i64, &'static str> {
    if !((value.clone()).contains_key(key.as_str())) {
        return Err("Kubernetes status keyr is missing");
    }
    Ok(non_negative_int(String::new(), key.clone()).unwrap_or_else(|_| 0_i64))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn non_negative_int(mut value: String, mut key: String) -> Result<i64, &'static str> {
    Ok(0_i64)
}

pub const PUBLIC_EXPORTS: &[&str] = &["KubernetesApiFailureReason", "KubernetesApiInventoryError", "deployment_status_properties", "node_status_properties", "optional_non_negative_int", "pod_status_properties"];
