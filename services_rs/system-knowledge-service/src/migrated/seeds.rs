#[derive(Clone, Debug, Default, PartialEq)]
pub struct SeedSource {
    pub path: String,
    pub symbol: String,
    pub source_kind: String,
    pub authority_role: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct KnowledgeSeed {
    pub knowledge_id: String,
    pub subject_id: String,
    pub title: String,
    pub status: String,
    pub owner: String,
    pub question_aliases: Vec<String>,
    pub designed_behavior: Vec<String>,
    pub implemented_behavior: Vec<String>,
    pub limitations: Vec<String>,
    pub sources: Vec<SeedSource>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn doc(mut path: String, mut symbol: String, mut role: String) -> SeedSource {
    SeedSource::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn code(mut path: String, mut symbol: String) -> SeedSource {
    SeedSource::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["KnowledgeSeed", "REFERENCE_SEEDS", "SeedSource"];
