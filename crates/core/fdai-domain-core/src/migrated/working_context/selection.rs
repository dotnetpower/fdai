use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ContextTrustClass {
    #[default]
    TrustedInternal,
    UntrustedExternal,
}

impl ContextTrustClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::TrustedInternal => "trusted-internal",
            Self::UntrustedExternal => "untrusted-external",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelCapabilityMetadata {
    pub model_id: String,
    pub context_window: i64,
    pub supports_tools: bool,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ContextSelectionInput {
    pub entries: Vec<String>,
    pub trust_classes: BTreeMap<String, ContextTrustClass>,
    pub budget: String,
    pub model: Box<ModelCapabilityMetadata>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ContextSelectionOutput {
    pub selected_entry_ids: Vec<String>,
    pub manifest: String,
}

pub trait ContextSelectionPolicy {
    fn policy_id(&self) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["ContextSelectionInput", "ContextSelectionOutput", "ContextSelectionPolicy", "ContextTrustClass", "ModelCapabilityMetadata"];
