use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FixVerdict {
    #[default]
    FixedVerified,
    StillPresent,
    Inconclusive,
    NotApplicable,
}

impl FixVerdict {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::FixedVerified => "fixed_verified",
            Self::StillPresent => "still_present",
            Self::Inconclusive => "inconclusive",
            Self::NotApplicable => "not_applicable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProducerRun {
    pub producer: String,
    pub rules_version: String,
    pub completed: Option<bool>,
    pub truncated: bool,
    pub analyzed_paths: Vec<String>,
    pub full_repository: bool,
    pub supersedes: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScanCoverageReceipt {
    pub revision: String,
    pub catalog_versions: BTreeMap<String, String>,
    pub runs: Vec<ProducerRun>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BaselineIssue {
    pub issue_id: String,
    pub weakness_class: String,
    pub path: String,
    pub symbol: Option<String>,
    pub producers: Vec<String>,
    pub package: Option<String>,
    pub advisory_ids: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FixVerification {
    pub issue_id: String,
    pub claim: String,
    pub verdict: FixVerdict,
    pub reasons: Vec<String>,
}

pub const REVISION: &str = "^[0-9a-f]{40}([0-9a-f]{24})?$";
impl ScanCoverageReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn run_for(&self, mut producer: String) -> Option<ProducerRun> {
        if producer.is_empty() {
            return None;
        }
        None
    }
}

impl BaselineIssue {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_issue(mut issue: String) -> BaselineIssue {
        if issue.is_empty() {
            return Default::default();
        }
        Default::default()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn major(mut version: String) -> String {
    if version.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn coverage_gaps(mut issue: BaselineIssue, mut baseline: ScanCoverageReceipt, mut rescan: ScanCoverageReceipt) -> Vec<String> {
    let mut gaps: Vec<String> = Vec::<String>::new();
    if (major(String::new())) != (major(String::new())) {
        gaps.push(String::from("weakness-class catalog major version differs"));
    }
    gaps.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn still_present(mut issue: BaselineIssue, mut rescan_issues: Vec<String>) -> bool {
    for candidate in rescan_issues.clone() {
        if !(issue.advisory_ids.clone()).is_empty() {
            continue;
        }
        return true;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn matches_rescan(mut issue: BaselineIssue, mut rescan_issues: Vec<String>) -> bool {
    still_present(issue.clone(), rescan_issues.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn verify_fix_claims(mut claims: Vec<String>, mut baseline_issues: std::collections::BTreeMap<String, BaselineIssue>, mut baseline: ScanCoverageReceipt, mut rescan: ScanCoverageReceipt, mut rescan_issues: Vec<String>, mut claimed_revision: String) -> Result<Vec<FixVerification>, &'static str> {
    let mut results: Vec<FixVerification> = Vec::<FixVerification>::new();
    for claim in claims.clone() {
        let mut gaps: Vec<String> = coverage_gaps(Default::default(), baseline.clone(), rescan.clone());
        if !(gaps.clone()).is_empty() {
            results.push(FixVerification::default());
        } else if still_present(Default::default(), rescan_issues.clone()) {
            results.push(FixVerification::default());
        } else {
            results.push(FixVerification::default());
        }
    }
    Ok(results.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["BaselineIssue", "FixVerdict", "FixVerification", "ProducerRun", "ScanCoverageReceipt", "coverage_gaps", "matches_rescan", "verify_fix_claims"];
