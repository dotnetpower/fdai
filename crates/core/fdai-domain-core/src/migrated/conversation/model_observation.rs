use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationModelObservation {
    pub model: String,
    #[allow(clippy::type_complexity)]
    pub usage: Option<BTreeMap<String, i64>>,
    pub trace_call: BTreeMap<String, String>,
    pub prompt_replay_manifest: Option<String>,
}

impl ConversationModelObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.model.trim().is_empty() { return Err("model must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationModelResponse {
    pub proposal: BTreeMap<String, String>,
    pub observation: Box<ConversationModelObservation>,
}

pub const PUBLIC_EXPORTS: &[&str] = &["ConversationModelObservation", "ConversationModelResponse"];
