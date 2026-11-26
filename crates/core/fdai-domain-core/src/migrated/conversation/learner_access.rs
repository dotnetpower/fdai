#[derive(Clone, Debug, Default, PartialEq)]
pub struct LearnerTurnView {
    pub turn_id: String,
    pub conversation_id: String,
    pub role: String,
    pub recorded_at: String,
    pub body: Option<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn project_turn_for_learner(mut turn: String, mut preference: Option<String>) -> LearnerTurnView {
    LearnerTurnView::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["LearnerTurnView", "project_turn_for_learner"];
