#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureConfig {
    pub tenant_id: Option<String>,
    pub subscription_id: String,
    pub resource_group: String,
    pub region: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct KafkaConfig {
    pub bootstrap_servers: String,
    pub security_protocol: String,
    pub sasl_mechanism: String,
    pub topic_events: String,
    pub topic_dlq_suffix: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresConfig {
    pub host: String,
    pub database: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleCatalogConfig {
    pub r#ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuntimeConfig {
    pub env: String,
    pub autonomy_mode_default: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LlmConfig {
    pub mode: String,
    pub resolved_models_path: Option<String>,
    pub resolved_models_sha256: Option<String>,
    pub capabilities: Vec<String>,
    pub t1_similarity_threshold: f64,
    pub t1_min_success_rate: f64,
    pub quality_gate_confidence_threshold: f64,
    pub quality_gate_quorum: i64,
    pub self_consistency_samples: i64,
    pub self_consistency_sample_threshold: f64,
    pub self_consistency_stability_threshold: f64,
    pub t2_primary_latency_routing: bool,
}

impl LlmConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(2_i64..=9223372036854775807_i64).contains(&self.quality_gate_quorum) { return Err("quality_gate_quorum out of bounds"); }
        if !(0_i64..=9_i64).contains(&self.self_consistency_samples) { return Err("self_consistency_samples out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleGovernanceConfig {
    pub exemption_max_duration_days: i64,
    pub exemption_alert_lead_days: i64,
}

impl RuleGovernanceConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=3650_i64).contains(&self.exemption_max_duration_days) { return Err("exemption_max_duration_days out of bounds"); }
        if !(1_i64..=365_i64).contains(&self.exemption_alert_lead_days) { return Err("exemption_alert_lead_days out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AppConfig {
    pub schema_version: String,
    pub azure: Box<AzureConfig>,
    pub kafka: Box<KafkaConfig>,
    pub postgres: Box<PostgresConfig>,
    pub rule_catalog: Box<RuleCatalogConfig>,
    pub runtime: Box<RuntimeConfig>,
    pub product_profile: String,
    pub llm: Box<LlmConfig>,
    pub rule_governance: Box<RuleGovernanceConfig>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ConfigBase {
    pub initialized: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct KafkaSecurityProtocol {
    pub initialized: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RuntimeEnv {
    pub initialized: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LlmMode {
    pub initialized: bool,
}

impl LlmConfig {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn model_post_init(&self, mut context: String) -> Result<(), &'static str> {
        if ((((self.capabilities.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.capabilities.clone()).len() as i64)) {
            return Err("llm.capabilities MUST NOT contain duplicates");
        }
        for cap in self.capabilities.clone() {
            if ((cap.clone()).is_empty()) || (!((cap.clone()).contains("."))) {
                return Err("llm.capabilities entry capr MUST match  tier.name e.g. t1.embedding");
            }
        }
        Ok(())
    }
}

impl RuleGovernanceConfig {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn model_post_init(&self, mut context: String) -> Result<(), &'static str> {
        if (self.exemption_alert_lead_days) >= (self.exemption_max_duration_days) {
            return Err("rule_governance.exemption_alert_lead_days MUST be strictly less than  ex");
        }
        Ok(())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AppConfig", "AzureConfig", "KafkaConfig", "LlmConfig", "LlmMode", "PostgresConfig", "RuleCatalogConfig", "RuleGovernanceConfig", "RuntimeConfig", "RuntimeEnv"];
