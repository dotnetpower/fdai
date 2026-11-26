#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProgrammaticPipelineStatus {
    #[default]
    Succeeded,
    Rejected,
    Failed,
    TimedOut,
    Cancelled,
    Incomplete,
}

impl ProgrammaticPipelineStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Succeeded => "succeeded",
            Self::Rejected => "rejected",
            Self::Failed => "failed",
            Self::TimedOut => "timed_out",
            Self::Cancelled => "cancelled",
            Self::Incomplete => "incomplete",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProgrammaticCallStatus {
    #[default]
    Succeeded,
    Rejected,
    Failed,
}

impl ProgrammaticCallStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Succeeded => "succeeded",
            Self::Rejected => "rejected",
            Self::Failed => "failed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProgrammaticPipelineLimits {
    pub timeout_seconds: f64,
    pub max_input_items: i64,
    pub max_input_bytes: i64,
    pub max_tool_calls: i64,
    pub max_call_input_bytes: i64,
    pub max_call_output_bytes: i64,
    pub max_stdout_bytes: i64,
    pub max_stderr_bytes: i64,
    pub max_final_json_bytes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProgrammaticToolPipelineRequest {
    pub run_id: String,
    pub reviewed_source: String,
    pub reviewed_source_digest: String,
    pub idempotency_key: String,
    pub input_json: Vec<String>,
    pub allowed_read_tools: Vec<String>,
    pub sandbox_profile_id: String,
    pub limits: Box<ProgrammaticPipelineLimits>,
}

impl ProgrammaticToolPipelineRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.run_id.trim().is_empty() { return Err("run_id must be non-empty"); }
        if self.reviewed_source.trim().is_empty() { return Err("reviewed_source must be non-empty"); }
        if self.reviewed_source_digest.trim().is_empty() { return Err("reviewed_source_digest must be non-empty"); }
        if self.idempotency_key.trim().is_empty() { return Err("idempotency_key must be non-empty"); }
        if self.sandbox_profile_id.trim().is_empty() { return Err("sandbox_profile_id must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProgrammaticPipelineCallReceipt {
    pub run_id: String,
    pub call_id: String,
    pub tool_id: String,
    pub sequence: i64,
    pub status: ProgrammaticCallStatus,
    pub input_digest: String,
    pub output_digest: Option<String>,
    pub receipt_ref: String,
    pub started_at: String,
    pub finished_at: String,
    pub latency_ms: i64,
    pub input_bytes: i64,
    pub output_bytes: i64,
    pub error_code: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProgrammaticPipelineStats {
    pub tool_calls: i64,
    pub succeeded_calls: i64,
    pub failed_calls: i64,
    pub input_bytes: i64,
    pub output_bytes: i64,
    pub duration_ms: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProgrammaticToolPipelineResult {
    pub run_id: String,
    pub status: ProgrammaticPipelineStatus,
    pub source_digest: String,
    pub stdout: String,
    pub stderr: String,
    pub final_json: Option<String>,
    pub receipt_refs: Vec<String>,
    pub stats: Box<ProgrammaticPipelineStats>,
    pub complete: bool,
    pub detail: Option<String>,
    pub truncated: bool,
}

pub const DIGEST: &str = "^[0-9a-f]{64}$";
pub const BOUNDED_ID: &str = "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$";
impl ProgrammaticToolPipelineResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn compact_projection(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("run_id"), self.run_id.clone()), (String::from("status"), String::new()), (String::from("complete"), String::new()), (String::from("final"), String::new()), (String::from("receipt_refs"), String::new()), (String::from("stats"), String::new()), (String::from("truncated"), String::new()), (String::from("detail"), (self.detail.clone()).unwrap_or_default())])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProgrammaticCallStatus", "ProgrammaticPipelineCallReceipt", "ProgrammaticPipelineLimits", "ProgrammaticPipelineStats", "ProgrammaticPipelineStatus", "ProgrammaticToolPipelineRequest", "ProgrammaticToolPipelineResult"];
