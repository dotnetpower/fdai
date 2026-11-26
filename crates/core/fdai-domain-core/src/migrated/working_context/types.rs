use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EntryKind {
    #[default]
    Verbatim,
    Summary,
    Retrieved,
    TypedFact,
}

impl EntryKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Verbatim => "verbatim",
            Self::Summary => "summary",
            Self::Retrieved => "retrieved",
            Self::TypedFact => "typed-fact",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EntryRole {
    #[default]
    Operator,
    Assistant,
    Tool,
    System,
    Agent,
}

impl EntryRole {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Operator => "operator",
            Self::Assistant => "assistant",
            Self::Tool => "tool",
            Self::System => "system",
            Self::Agent => "agent",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TranscriptEntry {
    pub entry_id: String,
    pub role: EntryRole,
    pub kind: EntryKind,
    pub text: String,
    pub tokens: i64,
    pub sequence: i64,
    pub pinned: bool,
    pub trusted: bool,
    pub level: i64,
    pub relevance: Option<f64>,
    pub source_ids: Vec<String>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ContextBudget {
    pub total_window: i64,
    pub base_reserve: i64,
    pub output_reserve: i64,
    pub tools_reserve: i64,
    pub memory_reserve: i64,
    pub verbatim_ratio: f64,
    pub retrieval_ratio: f64,
    pub summary_ratio: f64,
    pub typed_fact_ratio: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ContextManifest {
    pub verbatim_ids: Vec<String>,
    pub summary_ids: Vec<String>,
    pub retrieved_ids: Vec<String>,
    pub pinned_ids: Vec<String>,
    pub typed_fact_ids: Vec<String>,
    pub verbatim_tokens: i64,
    pub summary_tokens: i64,
    pub retrieved_tokens: i64,
    pub pinned_tokens: i64,
    pub typed_fact_tokens: i64,
    pub dropped_ids: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkingContext {
    pub entries: Vec<TranscriptEntry>,
    pub manifest: Box<ContextManifest>,
}

impl ContextBudget {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn history_budget(&self) -> i64 {
        (self.total_window).saturating_sub((self.base_reserve).saturating_sub((self.output_reserve).saturating_sub((self.tools_reserve).saturating_sub(self.memory_reserve))))
    }
}

impl ContextManifest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn total_tokens(&self) -> i64 {
        (self.verbatim_tokens).saturating_add((self.summary_tokens).saturating_add((self.retrieved_tokens).saturating_add((self.pinned_tokens).saturating_add(self.typed_fact_tokens))))
    }
}

impl WorkingContext {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn total_tokens(&self) -> i64 {
        0_i64
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct WorkingContextError {
    pub message: String,
}

impl WorkingContextError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for WorkingContextError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for WorkingContextError {}

pub const PUBLIC_EXPORTS: &[&str] = &["ContextBudget", "ContextManifest", "EntryKind", "EntryRole", "TranscriptEntry", "WorkingContext", "WorkingContextError"];
