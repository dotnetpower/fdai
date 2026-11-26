#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MscpFailureDisposition {
    #[default]
    HoldBeforeDispatch,
    HoldAfterDispatch,
    RecoverAfterDispatch,
}

impl MscpFailureDisposition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::HoldBeforeDispatch => "hold_before_dispatch",
            Self::HoldAfterDispatch => "hold_after_dispatch",
            Self::RecoverAfterDispatch => "recover_after_dispatch",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MscpFailureDecision {
    pub reason: String,
    pub disposition: MscpFailureDisposition,
    pub max_retry_attempts: i64,
    pub max_approval_requests: i64,
    pub demote_to_shadow: bool,
    pub execution_authority: bool,
}

impl MscpFailureDecision {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl MscpFailureDecision {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn retry_allowed(&self, mut attempts_used: i64) -> Result<bool, &'static str> {
        if (false) || (!(true)) {
            return Err("attempts_used MUST be an integer");
        }
        if (attempts_used) < (0_i64) {
            return Err("attempts_used MUST be non-negative");
        }
        Ok((attempts_used) < (self.max_retry_attempts))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn approval_allowed(&self, mut requests_used: i64) -> Result<bool, &'static str> {
        if (false) || (!(true)) {
            return Err("requests_used MUST be an integer");
        }
        if (requests_used) < (0_i64) {
            return Err("requests_used MUST be non-negative");
        }
        Ok((requests_used) < (self.max_approval_requests))
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn decide_mscp_failure(mut reason: String, mut profile_mode: String) -> Result<MscpFailureDecision, &'static str> {
    Err("unsupported MSCP failure reason: reason")
}

pub const PUBLIC_EXPORTS: &[&str] = &["MscpFailureDecision", "MscpFailureDisposition", "decide_mscp_failure"];
