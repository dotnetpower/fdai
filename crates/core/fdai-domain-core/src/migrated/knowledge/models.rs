use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum KnowledgeSourceKind {
    #[default]
    Upload,
    Wiki,
    WebPage,
    Architecture,
    BestPractice,
    WorkloadDoc,
    Runbook,
}

impl KnowledgeSourceKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Upload => "upload",
            Self::Wiki => "wiki",
            Self::WebPage => "web_page",
            Self::Architecture => "architecture",
            Self::BestPractice => "best_practice",
            Self::WorkloadDoc => "workload_doc",
            Self::Runbook => "runbook",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CodeRepoProvider {
    #[default]
    Github,
    AzureDevops,
}

impl CodeRepoProvider {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Github => "github",
            Self::AzureDevops => "azure_devops",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RegisteredDocument {
    pub doc_id: String,
    pub source_ref: String,
    pub kind: KnowledgeSourceKind,
    pub title: String,
    pub chunk_count: i64,
    pub registered_by: String,
    pub registered_at: String,
    pub metadata: BTreeMap<String, String>,
}

impl RegisteredDocument {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.doc_id.trim().is_empty() { return Err("doc_id must be non-empty"); }
        if self.source_ref.trim().is_empty() { return Err("source_ref must be non-empty"); }
        if self.title.trim().is_empty() { return Err("title must be non-empty"); }
        if self.registered_by.trim().is_empty() { return Err("registered_by must be non-empty"); }
        if self.registered_at.trim().is_empty() { return Err("registered_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CodeRepoRegistration {
    pub repo_id: String,
    pub provider: CodeRepoProvider,
    pub repository: String,
    pub default_branch: String,
    pub registered_by: String,
    pub registered_at: String,
    pub secret_ref: Option<String>,
    pub enabled: bool,
    pub metadata: BTreeMap<String, String>,
}

impl CodeRepoRegistration {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.repo_id.trim().is_empty() { return Err("repo_id must be non-empty"); }
        if self.repository.trim().is_empty() { return Err("repository must be non-empty"); }
        if self.default_branch.trim().is_empty() { return Err("default_branch must be non-empty"); }
        if self.registered_by.trim().is_empty() { return Err("registered_by must be non-empty"); }
        if self.registered_at.trim().is_empty() { return Err("registered_at must be non-empty"); }
        Ok(())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CodeRepoProvider", "CodeRepoRegistration", "KnowledgeSourceKind", "RegisteredDocument"];
