pub const MAX_MODEL_CALLS_PER_TURN: i64 = 32;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SemanticModelCallProgress {
    pub schema_version: String,
    pub record_kind: String,
    pub request_id: String,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub progress_sequence: i64,
    pub call_index: i64,
    pub stage: String,
    pub status: String,
    pub model: Option<String>,
    pub started_at: String,
    pub completed_at: Option<String>,
    pub duration_ms: Option<i64>,
    pub prompt_tokens: Option<i64>,
    pub completion_tokens: Option<i64>,
    pub execution_authority: bool,
}

impl SemanticModelCallProgress {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.record_kind.as_str(), "model_call_progress") { return Err("invalid record_kind literal"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.turn_sequence) { return Err("turn_sequence out of bounds"); }
        if !(1_i64..=256_i64).contains(&self.progress_sequence) { return Err("progress_sequence out of bounds"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.call_index) { return Err("call_index out of bounds"); }
        if !matches!(self.stage.as_str(), "preflight" | "judgment" | "form" | "blind_review" | "concept_chooser" | "direction_reader" | "ambiguity_reader" | "frame" | "plan") { return Err("invalid stage literal"); }
        if !matches!(self.status.as_str(), "running" | "completed" | "failed") { return Err("invalid status literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl SemanticModelCallProgress {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn lifecycle_is_consistent(&self) -> Result<SemanticModelCallProgress, &'static str> {
        let ended: bool = (self.status.clone()) != (String::from("running"));
        if ((ended) != (self.completed_at.is_some())) || ((ended) != (self.duration_ms.is_some())) {
            return Err("only an ended model call carries its completion time and duration");
        }
        if (!(ended)) && ((self.prompt_tokens.is_some()) || (self.completion_tokens.is_some())) {
            return Err("a running model call has no measured token counts");
        }
        if (self.completed_at.is_some()) && (((self.completed_at.clone()).unwrap_or_default()) < (self.started_at.clone())) {
            return Err("model call progress MUST NOT end before it starts");
        }
        Ok(self.clone())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["MAX_MODEL_CALLS_PER_TURN", "MAX_MODEL_CALL_UPDATES_PER_TURN", "ModelCallStage", "ModelCallStatus", "SemanticModelCallProgress"];
