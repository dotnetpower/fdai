pub const MAX_ID: i64 = 256;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReadInvestigationOutcome {
    #[default]
    Matched,
    Ambiguous,
    None,
    Unavailable,
    Partial,
    TimedOut,
}

impl ReadInvestigationOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Matched => "matched",
            Self::Ambiguous => "ambiguous",
            Self::None => "none",
            Self::Unavailable => "unavailable",
            Self::Partial => "partial",
            Self::TimedOut => "timed_out",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationBudget {
    pub max_wall_seconds: i64,
    pub max_cost_microusd: i64,
    pub max_tool_calls: i64,
    pub max_results: i64,
    pub max_output_bytes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationRequest {
    pub requester_ref: String,
    pub conversation_ref: String,
    pub correlation_ref: String,
    pub intent: String,
    pub selector: String,
    pub lookback_seconds: i64,
    pub requested_evidence: Vec<String>,
    pub budget: Box<ReadInvestigationBudget>,
    pub idempotency_key: String,
    pub created_at: String,
    pub explicit_deep: bool,
    pub origin_channel_kind: String,
    pub origin_channel_id: Option<String>,
    pub origin_thread_id: Option<String>,
    pub origin_message_id: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationStep {
    pub tool_id: String,
    pub timeout_seconds: f64,
    pub max_results: i64,
    pub max_output_bytes: i64,
    pub fallback_rank: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationPlan {
    pub request: Box<ReadInvestigationRequest>,
    pub steps: Vec<ReadInvestigationStep>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationResult {
    pub request: Box<ReadInvestigationRequest>,
    pub outcome: ReadInvestigationOutcome,
    pub resolution: String,
    pub evidence: Vec<String>,
    pub receipts: Vec<String>,
    pub progress_kinds: Vec<String>,
    pub started_at: String,
    pub finished_at: String,
}

impl ReadInvestigationPlan {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn evidence_steps(&self) -> Vec<ReadInvestigationStep> {
        core::hint::black_box(Vec::new())
    }
}

impl ReadInvestigationResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn evidence_refs(&self) -> Vec<String> {
        core::hint::black_box(Vec::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn identifier(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ReadInvestigationBudget", "ReadInvestigationOutcome", "ReadInvestigationPlan", "ReadInvestigationRequest", "ReadInvestigationResult", "ReadInvestigationStep"];
