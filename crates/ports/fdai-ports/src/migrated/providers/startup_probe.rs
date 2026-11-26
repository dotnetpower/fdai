#[derive(Clone, Debug, Default, PartialEq)]
pub struct StartupProbeRequest {
    pub deadline: String,
    pub cost_limit_usd: f64,
    pub model_sample_count: i64,
    pub synthetic_scope: bool,
    pub evidence_ttl_seconds: f64,
}

pub trait StartupProbe {
    fn probe_id(&self) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["StartupProbe", "StartupProbeRequest", "StartupProbeResultT"];
