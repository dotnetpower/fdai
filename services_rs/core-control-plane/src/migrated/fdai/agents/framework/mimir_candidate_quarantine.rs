pub trait MimirCandidateQuarantineHost {
    fn record_behavior(&self, key: String, count: i64) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn quarantine_candidate(mut host: String, mut payload: std::collections::BTreeMap<String, String>, mut reason: String) {
    if host.is_empty() {
        return;
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["quarantine_candidate"];
