pub const MAX_RESULT_BYTES: i64 = 1000000;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ClaimStatus {
    #[default]
    FixedClaimed,
    MitigatedClaimed,
    ClaimedFalsePositive,
    StaleOrAlreadyFixed,
    Deferred,
    Failed,
    PlanOnly,
    NotAttempted,
}

impl ClaimStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::FixedClaimed => "fixed_claimed",
            Self::MitigatedClaimed => "mitigated_claimed",
            Self::ClaimedFalsePositive => "claimed_false_positive",
            Self::StaleOrAlreadyFixed => "stale_or_already_fixed",
            Self::Deferred => "deferred",
            Self::Failed => "failed",
            Self::PlanOnly => "plan_only",
            Self::NotAttempted => "not_attempted",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ValidationState {
    #[default]
    TestsPassed,
    TestsFailed,
    ManualValidationRequired,
    NotRun,
}

impl ValidationState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::TestsPassed => "tests_passed",
            Self::TestsFailed => "tests_failed",
            Self::ManualValidationRequired => "manual_validation_required",
            Self::NotRun => "not_run",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum NextStep {
    #[default]
    RescanRequired,
    AdjudicationRequired,
    None,
}

impl NextStep {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::RescanRequired => "rescan_required",
            Self::AdjudicationRequired => "adjudication_required",
            Self::None => "none",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PackRecord {
    pub pack_id: String,
    pub manifest_sha256: String,
    pub base_commit: String,
    pub issue_ids: Vec<String>,
    pub expires_at: String,
    pub revoked: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IssueClaim {
    pub issue_id: String,
    pub status: ClaimStatus,
    pub validation: ValidationState,
    pub commits: Vec<String>,
    pub next_step: NextStep,
    pub evidence: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ImportedRemediationResult {
    pub pack_id: String,
    pub final_head: String,
    pub claims: Vec<IssueClaim>,
}

pub const SHA: &str = "^[0-9a-f]{40}([0-9a-f]{24})?$";
pub const ISSUE: &str = "^FDAI-SEC-[0-9a-f]{12}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RemediationResultRejectedError {
    pub message: String,
}

impl RemediationResultRejectedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for RemediationResultRejectedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for RemediationResultRejectedError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn text(mut value: String, mut limit: i64) -> String {
    if !(true) {
        return String::from("");
    }
    let marker: String = (String::from("...")).chars().take((limit).max(0) as usize).collect::<String>();
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn import_remediation_result(mut raw: Vec<u8>, mut record: PackRecord, mut now: String) -> Result<ImportedRemediationResult, &'static str> {
    if (((raw.clone()).len() as i64)) > (MAX_RESULT_BYTES) {
        return Err("result_too_large");
    }
    if record.revoked {
        return Err("pack_revoked");
    }
    if (now.clone()) > (record.expires_at.clone()) {
        return Err("pack_expired record.expires_at.isoformat");
    }
    let mut claims: Vec<IssueClaim> = Vec::<IssueClaim>::new();
    let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    Ok(ImportedRemediationResult::default())
}

pub const PUBLIC_EXPORTS: &[&str] = &["MAX_RESULT_BYTES", "ClaimStatus", "ImportedRemediationResult", "IssueClaim", "NextStep", "PackRecord", "RemediationResultRejectedError", "ValidationState", "import_remediation_result"];
