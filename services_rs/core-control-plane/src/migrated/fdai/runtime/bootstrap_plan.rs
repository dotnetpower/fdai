#[derive(Clone, Debug, Default, PartialEq)]
pub struct IdentityRequests {
    pub telemetry: bool,
    pub configuration_drift: bool,
    pub diagnostic: bool,
    pub gateway: bool,
    pub case_history: bool,
    pub vertical_execution: bool,
    pub stewardship_health: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BootstrapPlan {
    pub start_consumer: bool,
    pub venue: Option<String>,
    pub identity_requests: Box<IdentityRequests>,
    pub requires_initial_identity: bool,
    pub consumer_requires_workload_identity: bool,
    pub github_change_feed_enabled: bool,
    pub chatops_enabled: bool,
    pub email_enabled: bool,
    pub auxiliary_kafka_bootstrap_servers: Option<String>,
    pub pantheon_object_topic: String,
    pub stage_topic: String,
    pub isolated_executor_authority_cutover: bool,
    pub diagnostic_kafka_bootstrap_servers: Option<String>,
    pub diagnostic_topic: Option<String>,
    pub diagnostic_metric_whitelist: Vec<String>,
    pub product_profile: String,
}

pub const AUXILIARY_KAFKA_BOOTSTRAP_ENV: &str = "FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS";
impl IdentityRequests {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn any_requested(&self) -> bool {
        (self.telemetry) || ((self.configuration_drift) || ((self.diagnostic) || ((self.gateway) || ((self.case_history) || ((self.vertical_execution) || (self.stewardship_health))))))
    }
}

impl BootstrapPlan {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn requires_channel_http_client(&self) -> bool {
        (self.github_change_feed_enabled) || ((self.chatops_enabled) || (self.email_enabled))
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn build_bootstrap_plan(mut llm_mode: String, mut environment: std::collections::BTreeMap<String, String>, mut product_profile: Option<String>) -> Result<BootstrapPlan, &'static str> {
    let start_consumer: bool = matches!((((environment.clone()).get("FDAI_START_CONSUMER").cloned().unwrap_or_else(|| String::from(""))).to_lowercase()).as_str(), "1" | "true");
    let mut identity_requests: IdentityRequests = IdentityRequests { configuration_drift: matches!(((((environment.clone()).get("FDAI_CONFIGURATION_DRIFT_ENABLED").cloned().unwrap_or_else(|| String::from(""))).trim().to_string()).to_lowercase()).as_str(), "1" | "true"), diagnostic: false, ..Default::default() };
    let auxiliary_bootstrap: String = ((environment.clone()).get(AUXILIARY_KAFKA_BOOTSTRAP_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    let diagnostic_bootstrap: String = ((environment.clone()).get("FDAI_DIAGNOSTIC_KAFKA_BOOTSTRAP_SERVERS").cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    let diagnostic_topic: String = ((environment.clone()).get("FDAI_DIAGNOSTIC_TOPIC").cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    let diagnostic_whitelist: Vec<String> = diagnostic_metric_whitelist(environment.clone()).unwrap_or_else(|_| Vec::new());
    if !(diagnostic_bootstrap.clone()).is_empty() {
        if !(start_consumer) {
            return Err("diagnostic Kafka ingestion requires FDAI_START_CONSUMER");
        }
        identity_requests = IdentityRequests { telemetry: identity_requests.telemetry, configuration_drift: identity_requests.configuration_drift, diagnostic: true, gateway: identity_requests.gateway, case_history: identity_requests.case_history, vertical_execution: identity_requests.vertical_execution, stewardship_health: identity_requests.stewardship_health, ..Default::default() };
    }
    Ok(BootstrapPlan { start_consumer: start_consumer, identity_requests: Box::new(identity_requests.clone()), auxiliary_kafka_bootstrap_servers: (Some(auxiliary_bootstrap.clone())).or_else(|| None), pantheon_object_topic: ((environment.clone()).get("FDAI_PANTHEON_OBJECT_TOPIC").cloned().unwrap_or_else(|| String::from("fdai.pantheon.objects"))).trim().to_string(), diagnostic_kafka_bootstrap_servers: (Some(diagnostic_bootstrap.clone())).or_else(|| None), diagnostic_topic: (Some(diagnostic_topic.clone())).or_else(|| None), diagnostic_metric_whitelist: diagnostic_whitelist.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn diagnostic_metric_whitelist(mut environment: std::collections::BTreeMap<String, String>) -> Result<Vec<String>, &'static str> {
    let raw: String = ((environment.clone()).get("FDAI_DIAGNOSTIC_METRIC_WHITELIST_JSON").cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    Ok(Vec::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["VERTICAL_IDENTITY_ENV", "BootstrapPlan", "IdentityRequests", "build_bootstrap_plan"];
