#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DialogueStateShadow {
    pub initialized: bool,
}

impl DialogueStateShadow {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn observe(&self, mut session_id: String, mut prior_turns: Vec<String>, mut delivered: Option<String>) -> Option<String> {
        if ((session_id.trim().to_string()).is_empty()) || ((prior_turns.clone()).is_empty()) {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ADAPTIVE_HISTORY_WINDOW", "DialogueStateShadow"];
