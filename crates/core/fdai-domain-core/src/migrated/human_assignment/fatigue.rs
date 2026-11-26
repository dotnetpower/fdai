#[derive(Clone, Debug, Default, PartialEq)]
pub struct HandoverFatiguePolicy {
    pub max_invitations_per_session: i64,
    pub max_invitations_per_week: i64,
    pub max_questions_per_session: i64,
    pub max_session_minutes: i64,
    pub snooze_hours: i64,
}

impl HandoverFatiguePolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn week_key(&self, mut at: String) -> Result<String, &'static str> {
        if at.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["HandoverFatiguePolicy"];
