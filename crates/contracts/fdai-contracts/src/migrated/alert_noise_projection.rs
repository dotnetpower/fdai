#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertProcessLink {
    pub process_id: String,
    pub workflow_ref: String,
    pub status: String,
    pub mode: String,
}

impl AlertProcessLink {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.status.as_str(), "pending" | "running" | "waiting" | "compensating" | "compensated" | "succeeded" | "failed" | "cancelled" | "timed_out") { return Err("invalid status literal"); }
        if !matches!(self.mode.as_str(), "shadow" | "enforce") { return Err("invalid mode literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertProposalDetail {
    pub plan_digest: String,
    pub baseline: String,
    pub evaluation: Option<String>,
    #[allow(clippy::type_complexity)]
    pub process: Option<Box<AlertProcessLink>>,
    pub recorded_at: String,
    pub execution_authority: String,
}

impl AlertProposalDetail {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn require_plan(&self, mut plan: String) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
}

