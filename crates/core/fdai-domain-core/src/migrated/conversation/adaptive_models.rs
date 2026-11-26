#[derive(Clone, Debug, Default, PartialEq)]
pub struct AdaptiveGoal {
    pub goal_id: String,
    pub kind: String,
    pub question: String,
    pub required: String,
}

impl AdaptiveGoal {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.goal_id.trim().is_empty() { return Err("goal_id must be non-empty"); }
        if self.question.trim().is_empty() { return Err("question must be non-empty"); }
        if self.required.trim().is_empty() { return Err("required must be non-empty"); }
        if !matches!(self.kind.as_str(), "knowledge" | "operational" | "environment_example") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AdaptivePlan {
    pub route: String,
    pub social_act: String,
    pub context_dependency: String,
    pub action_requested: String,
    pub goals: Vec<AdaptiveGoal>,
    #[allow(clippy::type_complexity)]
    pub draft: Option<Box<AdaptiveDraft>>,
}

impl AdaptivePlan {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.route.as_str(), "legacy" | "adaptive") { return Err("invalid route literal"); }
        if !matches!(self.social_act.as_str(), "none" | "greeting" | "thanks" | "farewell" | "self_introduction") { return Err("invalid social_act literal"); }
        if !matches!(self.context_dependency.as_str(), "none" | "active_thread" | "pending_decision") { return Err("invalid context_dependency literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AdaptiveSection {
    pub goal_id: String,
    pub text: String,
}

impl AdaptiveSection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.goal_id.trim().is_empty() { return Err("goal_id must be non-empty"); }
        if self.text.trim().is_empty() { return Err("text must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AdaptiveDraft {
    pub sections: Vec<AdaptiveSection>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AdaptiveReview {
    pub safe: String,
    pub complete: String,
    pub supported_goal_ids: Vec<String>,
    pub issues: Vec<String>,
}

impl AdaptiveReview {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.safe.trim().is_empty() { return Err("safe must be non-empty"); }
        if self.complete.trim().is_empty() { return Err("complete must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AdaptiveEvidence {
    pub status: String,
    pub content: String,
    pub evidence_refs: Vec<String>,
    pub limitation: Option<String>,
    pub authorities: Vec<String>,
}

impl AdaptiveEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.content.trim().is_empty() { return Err("content must be non-empty"); }
        if !matches!(self.status.as_str(), "answered" | "unavailable" | "held") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AdaptivePolicy {
    pub total_seconds: f64,
    pub per_stage_seconds: f64,
    pub max_calls: i64,
    pub max_tokens: i64,
    pub max_input_bytes: i64,
    pub reserved_output_tokens: i64,
    pub refinement_enabled: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Candidate {
    pub initialized: bool,
}

impl AdaptiveGoal {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn non_blank_question(&self) -> Result<AdaptiveGoal, &'static str> {
        if ((self.question.clone()).trim().to_string()).is_empty() {
            return Err("adaptive goal question must be non-empty");
        }
        Ok(self.clone())
    }
}

impl AdaptivePlan {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn goals_are_consistent(&self) -> Result<AdaptivePlan, &'static str> {
        Err("runtime_binding_required")
    }
}

impl AdaptiveSection {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn non_blank_text(&self) -> Result<AdaptiveSection, &'static str> {
        if ((self.text.clone()).trim().to_string()).is_empty() {
            return Err("adaptive section text must be non-empty");
        }
        Ok(self.clone())
    }
}

impl AdaptiveDraft {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn sections_are_unique(&self) -> Result<AdaptiveDraft, &'static str> {
        Err("runtime_binding_required")
    }
}

impl AdaptiveReview {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn unique_supported_goals(&self) -> Result<AdaptiveReview, &'static str> {
        if ((((self.supported_goal_ids.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.supported_goal_ids.clone()).len() as i64)) {
            return Err("adaptive review supported_goal_ids must be unique");
        }
        Ok(self.clone())
    }
}

