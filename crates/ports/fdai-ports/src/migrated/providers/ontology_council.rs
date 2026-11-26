pub const MAX_TEXT: i64 = 16384;
pub const MAX_CONTEXT_ITEMS: i64 = 10000;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CouncilDisposition {
    #[default]
    Propose,
    Unsupported,
    Abstain,
}

impl CouncilDisposition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Propose => "propose",
            Self::Unsupported => "unsupported",
            Self::Abstain => "abstain",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CouncilTargetKind {
    #[default]
    Object,
    Link,
}

impl CouncilTargetKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Object => "object",
            Self::Link => "link",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CouncilOperation {
    #[default]
    Add,
    Update,
    Remove,
    Supersede,
}

impl CouncilOperation {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Add => "add",
            Self::Update => "update",
            Self::Remove => "remove",
            Self::Supersede => "supersede",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilModelIdentity {
    pub publisher: String,
    pub family: String,
    pub version: String,
    pub deployment: String,
    pub binding: String,
    pub fault_domain: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilProperty {
    pub name: String,
    pub value: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilSemanticFields {
    pub numbers: Vec<String>,
    pub units: Vec<String>,
    pub comparators: Vec<String>,
    pub negated: bool,
    pub effective_from: Option<String>,
    pub effective_to: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilObjectDeclaration {
    pub name: String,
    pub properties: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilLinkDeclaration {
    pub name: String,
    pub from_type: String,
    pub to_type: String,
    pub properties: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilEntity {
    pub identity: String,
    pub object_type: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilAlias {
    pub alias: String,
    pub identity: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilTokenUsage {
    pub prompt_tokens: i64,
    pub completion_tokens: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilClaimPacket {
    pub claim_id: String,
    pub source_assertion: String,
    pub source_ref: String,
    pub source_lines: String,
    pub content_sha256: String,
    pub citation_digest: String,
    pub authority: String,
    pub ontology_release: String,
    pub graph_revision: String,
    pub object_types: Vec<CouncilObjectDeclaration>,
    pub links: Vec<CouncilLinkDeclaration>,
    pub entities: Vec<CouncilEntity>,
    pub aliases: Vec<CouncilAlias>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilVote {
    pub model_identity: Box<CouncilModelIdentity>,
    pub claim_id: String,
    pub citation_digest: String,
    pub disposition: CouncilDisposition,
    pub operation: Option<CouncilOperation>,
    pub target_kind: Option<CouncilTargetKind>,
    pub target_type: Option<String>,
    pub target_identity: Option<String>,
    pub authority: Option<String>,
    pub properties: Vec<CouncilProperty>,
    pub from_identity: Option<String>,
    pub to_identity: Option<String>,
    pub semantics: Box<CouncilSemanticFields>,
    pub usage: Box<CouncilTokenUsage>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilFieldAlternative {
    pub digest: String,
    pub value_json: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilFieldDifference {
    pub field_name: String,
    pub value_digests: Vec<String>,
    pub alternatives: Vec<CouncilFieldAlternative>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilAgreedField {
    pub field_name: String,
    pub alternative: Box<CouncilFieldAlternative>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilDispute {
    pub claim_id: String,
    pub packet_digest: String,
    pub initial_vote_digests: String,
    pub differences: Vec<CouncilFieldDifference>,
    pub agreed_fields: Vec<CouncilAgreedField>,
}

pub const PROPERTY: &str = "^[a-z][a-z0-9_]{0,63}$";
impl CouncilModelIdentity {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        stable_digest(String::new())
    }
}

impl CouncilClaimPacket {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        stable_digest(String::new())
    }
}

impl CouncilVote {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        stable_digest(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn semantic_fingerprint(&self) -> Option<String> {
        Some(stable_digest(String::new()))
    }
}

pub trait OntologyCouncilModel {
    fn blind_vote(&self, packet: CouncilClaimPacket) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn stable_digest(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn dataclass_payload(mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn reject_json_constant(mut value: String) -> Result<(), &'static str> {
    Err("ValueError")
}

pub const PUBLIC_EXPORTS: &[&str] = &["CouncilAgreedField", "CouncilAlias", "CouncilClaimPacket", "CouncilDisposition", "CouncilDispute", "CouncilFieldAlternative", "CouncilFieldDifference", "CouncilLinkDeclaration", "CouncilModelIdentity", "CouncilObjectDeclaration", "CouncilOperation", "CouncilOutcome", "CouncilProperty", "CouncilScalar", "CouncilSemanticFields", "CouncilTargetKind", "CouncilTokenUsage", "CouncilVote", "OntologyCouncilModel"];
