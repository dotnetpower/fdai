pub trait BlastRadiusCeiling {
    fn max_affected_resources(&self) -> Option<String>;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn blast_radius_refusal(mut action: String, mut ceiling: String) -> Option<String> {
    if action.is_empty() {
        return None;
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["BlastRadiusCeiling", "blast_radius_refusal"];
