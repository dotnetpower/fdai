#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AcceptancePreflightSimulator {
    pub initialized: bool,
}

impl AcceptancePreflightSimulator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn simulate(&self, mut run: String) -> String {
        let context: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("run"), run.clone())]);
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn failed(mut reason: String) -> String {
    if reason.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["AcceptancePreflightSimulator"];
