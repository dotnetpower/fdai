#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DocumentKind {
    #[default]
    Raci,
    OnCall,
    OrgChart,
    Runbook,
    HandoverMemo,
    Other,
}

impl DocumentKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Raci => "raci",
            Self::OnCall => "on_call",
            Self::OrgChart => "org_chart",
            Self::Runbook => "runbook",
            Self::HandoverMemo => "handover_memo",
            Self::Other => "other",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MappingSource {
    #[default]
    Deterministic,
    Model,
}

impl MappingSource {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Deterministic => "deterministic",
            Self::Model => "model",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DraftOutcome {
    #[default]
    Drafted,
    Abstained,
}

impl DraftOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Drafted => "drafted",
            Self::Abstained => "abstained",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HandoverDocument {
    pub doc_id: String,
    pub kind: DocumentKind,
    pub text: String,
    pub title: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceSpan {
    pub doc_id: String,
    pub line: i64,
    pub quote: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PersonRef {
    pub display_name: String,
    pub kind: String,
    pub oid: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExtractedMapping {
    pub agent_name: String,
    pub person: Box<PersonRef>,
    pub responsibility: String,
    pub confidence: f64,
    pub source: MappingSource,
    pub citations: Vec<SourceSpan>,
    pub rationale: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StewardMapDraft {
    pub version: i64,
    pub outcome: DraftOutcome,
    pub mappings: Vec<ExtractedMapping>,
    pub abstained: Vec<ExtractedMapping>,
    pub unresolved_people: Vec<PersonRef>,
    pub unmapped_agents: Vec<String>,
    pub warnings: Vec<String>,
}

impl SourceSpan {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("doc_id"), self.doc_id.clone()), (String::from("line"), String::new()), (String::from("quote"), self.quote.clone())])
    }
}

impl PersonRef {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn unresolved(&self) -> bool {
        self.oid.is_none()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("display_name"), self.display_name.clone()), (String::from("kind"), String::new()), (String::from("oid"), (self.oid.clone()).unwrap_or_default()), (String::from("unresolved"), String::new())])
    }
}

impl ExtractedMapping {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn grounded(&self) -> bool {
        (((self.citations.clone()).len() as i64)) > (0_i64)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("agent_name"), self.agent_name.clone()), (String::from("person"), String::new()), (String::from("responsibility"), String::new()), (String::from("confidence"), String::new()), (String::from("source"), String::new()), (String::from("citations"), String::new()), (String::from("rationale"), self.rationale.clone())])
    }
}

impl StewardMapDraft {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("version"), String::new()), (String::from("outcome"), String::new()), (String::from("mappings"), String::new()), (String::from("abstained"), String::new()), (String::from("unresolved_people"), String::new()), (String::from("unmapped_agents"), String::new()), (String::from("warnings"), String::new())])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["DocumentKind", "DraftOutcome", "ExtractedMapping", "HandoverDocument", "MappingSource", "PersonRef", "SourceSpan", "StewardMapDraft"];
