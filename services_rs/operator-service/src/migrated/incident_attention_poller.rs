pub trait IncidentAttentionReader {
    fn incident_attention(&self, query: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IncidentAttentionPoller {
    pub initialized: bool,
}

impl IncidentAttentionPoller {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read(&mut self, mut after_seq: Option<i64>) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["IncidentAttentionPoller", "IncidentAttentionReader"];
