use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum StartupPhase {
    #[default]
    StaticLoad,
    RequiredReachability,
    CapabilityWarmup,
    ActiveSmoke,
}

impl StartupPhase {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::StaticLoad => "static_load",
            Self::RequiredReachability => "required_reachability",
            Self::CapabilityWarmup => "capability_warmup",
            Self::ActiveSmoke => "active_smoke",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProbeCriticality {
    #[default]
    ProcessCritical,
    AuthorityCritical,
    Optional,
}

impl ProbeCriticality {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ProcessCritical => "process_critical",
            Self::AuthorityCritical => "authority_critical",
            Self::Optional => "optional",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProbeStatus {
    #[default]
    Passed,
    Failed,
    TimedOut,
    Crashed,
}

impl ProbeStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Passed => "passed",
            Self::Failed => "failed",
            Self::TimedOut => "timed_out",
            Self::Crashed => "crashed",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReadinessDecision {
    #[default]
    Ready,
    Degraded,
    Blocked,
}

impl ReadinessDecision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Ready => "ready",
            Self::Degraded => "degraded",
            Self::Blocked => "blocked",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AuthorityCeiling {
    #[default]
    Disabled,
    DeterministicFallback,
    Shadow,
    HumanApproval,
    Deployment,
}

impl AuthorityCeiling {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Disabled => "disabled",
            Self::DeterministicFallback => "deterministic_fallback",
            Self::Shadow => "shadow",
            Self::HumanApproval => "human_approval",
            Self::Deployment => "deployment",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EvidenceRequirement {
    #[default]
    Standard,
    ModelStream,
    ModelEmbedding,
    ModelStructuredOutput,
    ModelToolCalling,
}

impl EvidenceRequirement {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Standard => "standard",
            Self::ModelStream => "model_stream",
            Self::ModelEmbedding => "model_embedding",
            Self::ModelStructuredOutput => "model_structured_output",
            Self::ModelToolCalling => "model_tool_calling",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StartupProbeSpec {
    pub probe_id: String,
    pub capability: String,
    pub phase: StartupPhase,
    pub criticality: ProbeCriticality,
    pub failure_ceiling: AuthorityCeiling,
    pub evidence_requirement: EvidenceRequirement,
    pub estimated_cost_usd: f64,
    pub synthetic_scope: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelStartupEvidence {
    pub sample_count: i64,
    pub total_latency_ms: Vec<f64>,
    pub ttft_ms: Vec<f64>,
    pub output_token_rate: Vec<f64>,
    pub embedding_dimensions: Option<i64>,
    pub structured_output_proven: bool,
    pub tool_calling_proven: bool,
    pub ttft_p95_ms: Option<f64>,
}

impl ModelStartupEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(2_i64..=9223372036854775807_i64).contains(&self.sample_count) { return Err("sample_count out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StartupProbeResult {
    pub probe_id: String,
    pub status: ProbeStatus,
    pub observed_at: String,
    pub expires_at: String,
    pub latency_ms: f64,
    pub failure_class: Option<String>,
    pub evidence: BTreeMap<String, bool>,
    #[allow(clippy::type_complexity)]
    pub model_evidence: Option<Box<ModelStartupEvidence>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StartupReadinessReport {
    pub generated_at: String,
    pub decision: ReadinessDecision,
    pub results: Vec<StartupProbeResult>,
    pub missing_probe_ids: Vec<String>,
    pub stale_probe_ids: Vec<String>,
    pub authority_ceilings: BTreeMap<String, AuthorityCeiling>,
    pub decision_evidence_receipt_digest: Option<String>,
    pub decision_evidence_verification_bundle_digest: Option<String>,
    pub decision_evidence_rejection_reasons: Vec<String>,
}

impl StartupProbeSpec {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_process_ceiling(&self) -> Result<StartupProbeSpec, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ModelStartupEvidence {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_samples(&self) -> Result<ModelStartupEvidence, &'static str> {
        if (((self.total_latency_ms.clone()).len() as i64)) != (self.sample_count) {
            return Err("model total-latency samples MUST match sample_count");
        }
        if (!(self.ttft_ms.clone()).is_empty()) && ((((self.ttft_ms.clone()).len() as i64)) != (self.sample_count)) {
            return Err("model TTFT samples MUST match sample_count");
        }
        if (!(self.output_token_rate.clone()).is_empty()) && ((((self.output_token_rate.clone()).len() as i64)) != (self.sample_count)) {
            return Err("model output-token-rate samples MUST match sample_count");
        }
        if (self.ttft_p95_ms.is_some()) && ((self.sample_count) < (20_i64)) {
            return Err("model TTFT p95 requires at least 20 startup samples");
        }
        Ok(self.clone())
    }
}

impl StartupProbeResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_timezone(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_result(&self) -> Result<StartupProbeResult, &'static str> {
        if (self.expires_at.clone()) <= (self.observed_at.clone()) {
            return Err("startup evidence expiry MUST follow observation time");
        }
        Ok(self.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn reject_sensitive_evidence(mut value: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        for (key, item) in value.clone() {
            let normalized_key: String = key.to_lowercase();
        }
        Ok(value.clone())
    }
}

impl StartupReadinessReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_json(&self) -> String {
        core::hint::black_box(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn more_restrictive(mut left: AuthorityCeiling, mut right: AuthorityCeiling) -> AuthorityCeiling {
    core::hint::black_box(Default::default())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AuthorityCeiling", "EvidenceRequirement", "ModelStartupEvidence", "ProbeCriticality", "ProbeStatus", "ReadinessDecision", "StartupPhase", "StartupProbeResult", "StartupProbeSpec", "StartupReadinessReport", "more_restrictive"];
