#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReviewProfile {
    #[default]
    Code,
    Security,
    All,
}

impl ReviewProfile {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Code => "code",
            Self::Security => "security",
            Self::All => "all",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FindingSeverity {
    #[default]
    Critical,
    High,
    Medium,
    Low,
}

impl FindingSeverity {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Critical => "critical",
            Self::High => "high",
            Self::Medium => "medium",
            Self::Low => "low",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PullRequestFile {
    pub path: String,
    pub status: String,
    pub additions: i64,
    pub deletions: i64,
    pub patch: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PullRequestSnapshot {
    pub repository: String,
    pub pull_number: i64,
    pub base_sha: String,
    pub head_sha: String,
    pub changed_files: i64,
    pub files: Vec<PullRequestFile>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReviewFinding {
    pub rule_id: String,
    pub severity: FindingSeverity,
    pub category: String,
    pub path: String,
    pub line: i64,
    pub message: String,
    pub evidence_sha256: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReviewReport {
    pub repository: String,
    pub pull_number: i64,
    pub base_sha: String,
    pub head_sha: String,
    pub profile: ReviewProfile,
    pub changed_files: i64,
    pub reviewed_files: i64,
    pub omitted_patch_files: Vec<String>,
    pub findings: Vec<ReviewFinding>,
}

impl ReviewFinding {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("rule_id"), self.rule_id.clone()), (String::from("severity"), String::new()), (String::from("category"), self.category.clone()), (String::from("path"), self.path.clone()), (String::from("line"), String::new()), (String::from("message"), self.message.clone()), (String::from("evidence_sha256"), self.evidence_sha256.clone())])
    }
}

impl ReviewReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.code-assurance.review.v1")), (String::from("repository"), self.repository.clone()), (String::from("pull_number"), String::new()), (String::from("base_sha"), self.base_sha.clone()), (String::from("head_sha"), self.head_sha.clone()), (String::from("profile"), String::new()), (String::from("changed_files"), String::new()), (String::from("reviewed_files"), String::new()), (String::from("omitted_patch_files"), String::new()), (String::from("coverage_complete"), String::new()), (String::from("finding_count"), String::new()), (String::from("findings"), String::new())])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["FindingSeverity", "PullRequestFile", "PullRequestSnapshot", "ReviewFinding", "ReviewProfile", "ReviewReport"];
