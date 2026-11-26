#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AbstainResponder {
    pub initialized: bool,
}

impl AbstainResponder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn respond(&self, mut composed_prompt: String, mut capability_id: String) -> (std::collections::BTreeMap<String, String>, String) {
        (std::collections::BTreeMap::new(), String::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RecordingResponder {
    pub initialized: bool,
}

impl RecordingResponder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn respond(&self, mut composed_prompt: String, mut capability_id: String) -> Result<(Option<std::collections::BTreeMap<String, String>>, String), &'static str> {
        Ok((None, String::new()))
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AbstainResponder", "RecordingResponder"];
