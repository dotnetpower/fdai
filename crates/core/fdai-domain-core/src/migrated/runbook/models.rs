use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RunbookStepOutcome {
    #[default]
    Success,
    Failure,
    Skipped,
    Waiting,
}

impl RunbookStepOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::Failure => "failure",
            Self::Skipped => "skipped",
            Self::Waiting => "waiting",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RunbookStep {
    pub id: String,
    pub action_type: String,
    pub params: BTreeMap<String, String>,
    pub on_failure: Option<String>,
    pub kind: String,
    pub wait_for: Option<String>,
    pub timeout_seconds: Option<i64>,
    pub approval_role: Option<String>,
    pub quorum: i64,
    pub no_self_approval: bool,
    pub outcomes: Vec<String>,
    pub branches: Vec<String>,
    pub guard_rule_ref: Option<String>,
}

impl RunbookStep {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.id.trim().is_empty() { return Err("id must be non-empty"); }
        if self.action_type.trim().is_empty() { return Err("action_type must be non-empty"); }
        if self.kind.trim().is_empty() { return Err("kind must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Runbook {
    pub id: String,
    pub steps: Vec<RunbookStep>,
    pub description: Option<String>,
    pub schema_version: String,
}

impl Runbook {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.id.trim().is_empty() { return Err("id must be non-empty"); }
        if self.schema_version.trim().is_empty() { return Err("schema_version must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RunbookStepResult {
    pub step_id: String,
    pub action_type: String,
    pub outcome: RunbookStepOutcome,
    pub reason: Option<String>,
}

impl RunbookStepResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.step_id.trim().is_empty() { return Err("step_id must be non-empty"); }
        if self.action_type.trim().is_empty() { return Err("action_type must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RunbookResult {
    pub runbook_id: String,
    pub step_results: Vec<RunbookStepResult>,
    pub terminal_outcome: RunbookStepOutcome,
}

impl RunbookResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.runbook_id.trim().is_empty() { return Err("runbook_id must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RunbookRunError {
    pub message: String,
}

impl RunbookRunError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for RunbookRunError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for RunbookRunError {}

pub const PUBLIC_EXPORTS: &[&str] = &["Runbook", "RunbookResult", "RunbookRunError", "RunbookStep", "RunbookStepOutcome", "RunbookStepResult"];
