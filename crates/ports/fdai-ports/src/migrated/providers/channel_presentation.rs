use std::collections::BTreeMap;
pub const MAX_PRESENTATION_FACTS: i64 = 256;
pub const MAX_PRESENTATION_SECTIONS: i64 = 8;
pub const MAX_PRESENTATION_LIMITATIONS: i64 = 16;
pub const MAX_PRESENTATION_TEXT_CHARS: i64 = 16000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelPresentationCapabilities {
    pub profile_id: String,
    pub max_text_chars: i64,
    pub max_serialized_bytes: i64,
    pub max_blocks: i64,
    pub max_block_text_chars: i64,
    pub max_fields: i64,
    pub max_actions: i64,
    pub supports_images: bool,
    pub supports_deterministic_sparkline: bool,
    pub supports_edits: bool,
    pub supports_threads: bool,
    pub supports_progress: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelPresentationFact {
    pub label: String,
    pub value: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelPresentationSection {
    pub kind: String,
    pub title: String,
    pub facts: Vec<ChannelPresentationFact>,
    pub description: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelPresentationEnvelope {
    pub canonical_text: String,
    pub artifact_version: Option<i64>,
    pub sections: Vec<ChannelPresentationSection>,
    pub limitations: Vec<String>,
    pub evidence_refs: Vec<String>,
    pub authority: String,
    pub unavailable: bool,
    pub web_url: Option<String>,
    pub artifact_degraded: bool,
    pub execution_authority: bool,
}

impl ChannelPresentationEnvelope {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelPresentationPayload {
    pub renderer_id: String,
    pub body: BTreeMap<String, String>,
    pub fallback_text: String,
    pub degraded_to_text: bool,
    pub omitted_visuals: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChannelPresentationRenderError {
    pub message: String,
}

impl ChannelPresentationRenderError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ChannelPresentationRenderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ChannelPresentationRenderError {}

pub trait ChannelPresentationRenderer {
    fn render(&self, envelope: ChannelPresentationEnvelope) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bounded_text(mut name: String, mut value: String, mut maximum: i64) -> Result<(), &'static str> {
    if ((value.clone()).is_empty()) || ((((value.clone()).trim().to_string()).is_empty()) || ((((value.clone()).len() as i64)) > (maximum))) {
        return Err("channel presentation name MUST be bounded and non-empty");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChannelPresentationCapabilities", "ChannelPresentationEnvelope", "ChannelPresentationFact", "ChannelPresentationPayload", "ChannelPresentationRenderError", "ChannelPresentationRenderer", "ChannelPresentationSection", "MAX_PRESENTATION_FACTS"];
