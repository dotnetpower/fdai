pub const MAX_CONVERSATION_ID_CHARS: i64 = 256;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DialogueStateRetention {
    pub writer: Option<String>,
    pub proposer: Option<String>,
}

pub trait DialogueSnapshotWriter {
    fn append(&self, principal_id: String, conversation_id: String, state: String, recorded_at: String) -> String;
}

impl DialogueStateRetention {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn retain(&self, mut principal_id: String, mut conversation_id: String, mut state: String, mut turns: Vec<String>) -> bool {
        if self.proposer.is_none() {
            return false;
        }
        true
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn propose_and_retain(&self, mut principal_id: String, mut conversation_id: String, mut state: String, mut turns: Vec<String>) {
        if principal_id.is_empty() {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn aclose(&self) {
        core::sync::atomic::compiler_fence(core::sync::atomic::Ordering::SeqCst);
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn history_dialogue_turns(mut history: Vec<(String, String)>) -> Vec<String> {
    if history.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn shadow_dialogue_state(mut history: Vec<(String, String)>, mut kept: i64) -> String {
    if history.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn dialogue_shadow_receipt(mut state: String) -> String {
    if state.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn retain_dialogue_shadow(mut writer: Option<String>, mut principal_id: String, mut conversation_id: String, mut state: String, mut clock: String) {
    if writer.is_none() {
        return;
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["DialogueSnapshotWriter", "DialogueStateRetention", "dialogue_shadow_receipt", "history_dialogue_turns", "retain_dialogue_shadow", "shadow_dialogue_state"];
