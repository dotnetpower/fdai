use std::collections::BTreeMap;
pub const EMBEDDING_DIM: i64 = 384;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BehaviorSource {
    pub source_kind: String,
    pub path: String,
    pub symbol: String,
    pub line_start: i64,
    pub line_end: i64,
    pub blob_sha: String,
    pub authority_role: String,
}

impl BehaviorSource {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.source_kind.as_str(), "code" | "test" | "doc" | "schema") { return Err("invalid source_kind literal"); }
        if !matches!(self.authority_role.as_str(), "implementation" | "verification" | "design" | "configuration") { return Err("invalid authority_role literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BehaviorContent {
    pub trigger: Vec<String>,
    pub preconditions: Vec<String>,
    pub steps: Vec<String>,
    pub outcomes: Vec<String>,
    pub exclusions: Vec<String>,
    pub safety: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BehaviorSpec {
    pub behavior_id: String,
    pub subject_kind: String,
    pub subject_id: String,
    pub status: String,
    pub owner: String,
    pub question_aliases: Vec<String>,
    pub trigger: Vec<String>,
    pub preconditions: Vec<String>,
    pub steps: Vec<String>,
    pub outcomes: Vec<String>,
    pub exclusions: Vec<String>,
    pub safety: Vec<String>,
    pub sources: Vec<BehaviorSource>,
    pub indexed_commit: String,
    pub extractor_version: String,
    pub source_manifest_hash: String,
    pub localized: BTreeMap<String, BehaviorContent>,
    pub embedding: Vec<f64>,
}

impl BehaviorSpec {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.status.as_str(), "implemented" | "configured" | "designed" | "not_applicable") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BehaviorFreshness {
    pub fresh: bool,
    pub tracked: bool,
    pub current_blob_sha: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BehaviorSearchResult {
    pub spec: Box<BehaviorSpec>,
    pub score: f64,
    pub match_kind: String,
    pub stale: bool,
    pub stale_sources: Vec<BehaviorSource>,
}

impl BehaviorSearchResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.match_kind.as_str(), "exact_alias" | "exact_identifier" | "hybrid") { return Err("invalid match_kind literal"); }
        Ok(())
    }
}

impl BehaviorSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn citation(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("path"), self.path.clone()), (String::from("symbol"), self.symbol.clone()), (String::from("line_start"), String::new()), (String::from("line_end"), String::new()), (String::from("blob_sha"), self.blob_sha.clone())])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn manifest_record(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("source_kind"), self.source_kind.clone()), (String::from("authority_role"), self.authority_role.clone())])
    }
}

impl BehaviorContent {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn search_text(&self) -> String {
        core::hint::black_box(String::new())
    }
}

impl BehaviorSpec {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn test_backed(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn search_text(&self) -> String {
        core::hint::black_box(String::new())
    }
}

pub trait BehaviorSourceValidator {
    fn py_validate(&self, source: BehaviorSource) -> String;
}

pub trait BehaviorKnowledgeIndex {
    fn upsert(&self, spec: BehaviorSpec) -> bool;
    fn search(&self, query: String, k: i64) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["BehaviorAuthorityRole", "BehaviorContent", "BehaviorFreshness", "BehaviorKnowledgeIndex", "BehaviorMatchKind", "BehaviorSearchResult", "BehaviorSource", "BehaviorSourceKind", "BehaviorSourceValidator", "BehaviorSpec", "BehaviorStatus", "EMBEDDING_DIM", "Embedder"];
