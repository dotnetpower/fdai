use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct WebSearchQuery {
    pub text: String,
    pub allowed_domains: Vec<String>,
    pub max_results: i64,
    pub budget_ms: i64,
    pub metadata: BTreeMap<String, String>,
}

impl WebSearchQuery {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.text.trim().is_empty() { return Err("text must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WebSnippet {
    pub url: String,
    pub domain: String,
    pub title: String,
    pub text: String,
    pub content_hash: String,
    pub fetched_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WebCitation {
    pub source_hash: String,
    pub start_index: i64,
    pub end_index: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WebSearchResult {
    pub query: Box<WebSearchQuery>,
    pub snippets: Vec<WebSnippet>,
    pub answer: String,
    pub citations: Vec<WebCitation>,
    pub provider_ref: Option<String>,
    pub execution_receipt_digest: Option<String>,
    pub reasons: Vec<String>,
}

pub const PUBLIC_EXPORTS: &[&str] = &["WebCitation", "WebSearchQuery", "WebSearchResult", "WebSnippet"];
