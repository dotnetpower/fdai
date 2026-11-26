#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PreflightCheckOutcome {
    #[default]
    Posted,
    AlreadyPosted,
    PublishError,
}

impl PreflightCheckOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Posted => "posted",
            Self::AlreadyPosted => "already_posted",
            Self::PublishError => "publish_error",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PreflightCheckResult {
    pub outcome: PreflightCheckOutcome,
    pub receipt: Option<String>,
    pub error_message: Option<String>,
    pub check: Option<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn publish_preflight_check(mut publisher: String, mut pr_ref: String, mut check_key: String, mut report: String, mut metadata: Option<std::collections::BTreeMap<String, String>>) -> Result<PreflightCheckResult, &'static str> {
    if ((pr_ref.clone()).trim().to_string()).is_empty() {
        return Err("pr_ref MUST be non-empty");
    }
    if ((check_key.clone()).trim().to_string()).is_empty() {
        return Err("check_key MUST be non-empty");
    }
    Ok(PreflightCheckResult::default())
}

pub const PUBLIC_EXPORTS: &[&str] = &["PreflightCheckOutcome", "PreflightCheckResult", "publish_preflight_check"];
