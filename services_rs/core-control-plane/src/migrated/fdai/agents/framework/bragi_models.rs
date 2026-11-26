use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct RoutingDecision {
    pub primary_agent: Option<String>,
    pub scores: BTreeMap<String, f64>,
    pub tie_break: Option<String>,
    pub contributors: Vec<String>,
    pub method: String,
    pub semantic_score: Option<f64>,
    pub semantic_margin: Option<f64>,
    pub provider_status: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Turn {
    pub turn_index: i64,
    pub question: String,
    pub primary_agent: Option<String>,
    pub answer: BTreeMap<String, String>,
    pub decision: Box<RoutingDecision>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationSession {
    pub session_id: String,
    pub user_id: String,
    pub created_at: Option<String>,
    pub last_active_at: Option<String>,
    pub ended_at: Option<String>,
    pub generation: i64,
    pub turns: Vec<Turn>,
    pub conversation_published: bool,
    pub conversation_publication_inflight: bool,
    pub next_turn_index: i64,
}

pub const PUBLIC_EXPORTS: &[&str] = &["ConversationSession", "RoutingDecision", "Turn"];
