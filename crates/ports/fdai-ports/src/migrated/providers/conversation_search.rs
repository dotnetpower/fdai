#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ConversationSearchMode {
    #[default]
    Terms,
    Phrase,
    Prefix,
}

impl ConversationSearchMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Terms => "terms",
            Self::Phrase => "phrase",
            Self::Prefix => "prefix",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationSearchScope {
    pub principal_id: String,
    pub allowed_channels: Vec<String>,
    pub allowed_conversation_ids: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationSearchQuery {
    pub text: String,
    pub mode: ConversationSearchMode,
    pub limit: i64,
    pub context_turns: i64,
    pub channels: Vec<String>,
    pub roles: Vec<String>,
    pub conversation_id: Option<String>,
    pub incident_id: Option<String>,
    pub correlation_id: Option<String>,
    pub recorded_after: Option<String>,
    pub recorded_before: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationTextRange {
    pub start: i64,
    pub end: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationSearchSnippet {
    pub text: String,
    pub highlights: Vec<ConversationTextRange>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationSearchHit {
    pub result_id: String,
    pub turn_id: String,
    pub conversation_id: String,
    pub channel_id: String,
    pub role: String,
    pub snippet: Box<ConversationSearchSnippet>,
    pub recorded_at: String,
    pub rank: f64,
    pub incident_id: Option<String>,
    pub correlation_id: Option<String>,
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationSearchPage {
    pub hits: Vec<ConversationSearchHit>,
    pub result_cap: i64,
    pub query_ms: f64,
    pub index_rows: i64,
    pub index_bytes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationSearchContext {
    pub hit: Box<ConversationSearchHit>,
    pub before: Vec<ConversationSearchHit>,
    pub after: Vec<ConversationSearchHit>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationLineage {
    pub conversation_id: String,
    pub channel_id: String,
    pub started_at: String,
    pub last_active: String,
    pub turn_ids: Vec<String>,
}

pub trait ConversationSearch {
    fn search(&self, scope: ConversationSearchScope, query: ConversationSearchQuery) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bounded_text(mut name: String, mut value: String, mut maximum: i64) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bounded_set(mut name: String, mut values: std::collections::BTreeSet<String>, mut maximum: i64) -> Result<(), &'static str> {
    if (((values.clone()).len() as i64)) > (maximum) {
        return Err("ConversationSearchScope.name exceeds cap");
    }
    for value in values.clone() {
        let _ = bounded_text(format!("ConversationSearchScope.{}", name.clone()), value.clone(), 256_i64).unwrap_or_else(|_| ());
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ConversationLineage", "ConversationSearch", "ConversationSearchContext", "ConversationSearchHit", "ConversationSearchMode", "ConversationSearchPage", "ConversationSearchQuery", "ConversationSearchScope", "ConversationSearchSnippet", "ConversationTextRange"];
