pub const MAX_PROPOSER_PROMPT_CHARS: i64 = 24000;

pub const DIALOGUE_T1_ENV: &str = "FDAI_NARRATOR_DIALOGUE_STATE_T1_ENABLED";
pub const TRUE: &[&str] = &["1", "true", "yes", "on"];
pub const FALSE: &[&str] = &["", "0", "false", "no", "off"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NarratorDialogueProposer {
    pub initialized: bool,
}

impl NarratorDialogueProposer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn propose(&self, mut turns: Vec<String>) -> Option<String> {
        parse(String::new(), std::collections::BTreeMap::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn dialogue_t1_enabled(mut values: std::collections::BTreeMap<String, String>) -> Result<bool, &'static str> {
    let raw: String = (((values.clone()).get(DIALOGUE_T1_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string()).to_lowercase();
    Err("DIALOGUE_T1_ENV MUST be a boolean")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn parse(mut answer: String, mut contents: std::collections::BTreeMap<String, String>) -> Option<String> {
    let mut anchors: Vec<String> = Vec::<String>::new();
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["DIALOGUE_T1_ENV", "MAX_PROPOSER_PROMPT_CHARS", "NarratorDialogueProposer", "dialogue_t1_enabled"];
