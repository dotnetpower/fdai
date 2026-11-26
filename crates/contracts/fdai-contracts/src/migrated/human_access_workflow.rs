#[derive(Clone, Debug, Default, PartialEq)]
pub struct HumanAccessWorkNotice {
    pub schema_version: String,
    pub request_id: String,
    pub operation: String,
    pub case_id: String,
    pub expected_revision: i64,
    pub action_id: Option<String>,
    pub approval_id: Option<String>,
    pub observed_at: String,
    pub expires_at: String,
}

impl HumanAccessWorkNotice {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.operation.as_str(), "request" | "decision" | "reconcile" | "resume" | "recovery") { return Err("invalid operation literal"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.expected_revision) { return Err("expected_revision out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HumanAccessHandoff {
    pub schema_version: String,
    pub notice: Box<HumanAccessWorkNotice>,
    pub stage: String,
    pub action_id: Option<String>,
    pub material_digest: Option<String>,
    pub evidence_ref: Option<String>,
    pub reason: Option<String>,
    pub execution_authority: bool,
}

impl HumanAccessHandoff {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.stage.as_str(), "proposed" | "awaiting_human" | "decision_checked" | "human_reviewed" | "prepared" | "dispatch_ready" | "dispatch_pending" | "dispatch_observed" | "effect_observed" | "effect_checked" | "effect_recorded" | "effect_mismatch" | "recovery_held" | "recovery_observed" | "recovery_judged" | "recovery_proposed" | "recovery_verified" | "recovery_recorded" | "held") { return Err("invalid stage literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HumanAccessMembershipObservation {
    pub schema_version: String,
    pub kind: String,
    pub material_digest: String,
    pub action_digest: String,
    pub target_digest: String,
    pub dispatch_receipt_digest: String,
    pub state: String,
    pub observer_identity_ref: String,
    pub source_ref: String,
    pub observed_at: String,
    pub valid_until: String,
}

impl HumanAccessMembershipObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.kind.as_str(), "human_access_membership_observation") { return Err("invalid kind literal"); }
        if !matches!(self.state.as_str(), "membership_present" | "membership_absent") { return Err("invalid state literal"); }
        Ok(())
    }
}

pub const HUMAN_ACCESS_EVENT_TYPE: &str = "human.assignment.execution.v1";
pub const HUMAN_ACCESS_WORK_KIND: &str = "human_access_execution";
impl HumanAccessWorkNotice {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_source(&self) -> Result<HumanAccessWorkNotice, &'static str> {
        if (self.operation.clone()) == (String::from("request")) {
            if (self.action_id.is_some()) || (self.approval_id.is_some()) {
                return Err("human access request cannot supply existing execution authority");
            }
        } else if (self.action_id.is_none()) || (((self.operation.clone()) == (String::from("decision"))) != (self.approval_id.is_some())) {
            return Err("human access phase requires its exact material and decision identity");
        }
        Ok(self.clone())
    }
}

impl HumanAccessHandoff {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn no_coerced_authority(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn references_only(&self) -> Result<HumanAccessHandoff, &'static str> {
        if (self.stage.clone()) == (String::from("held")) {
            if self.reason.is_none() {
                return Err("human access hold requires an explicit bounded reason");
            }
        } else if (self.action_id.is_none()) || (self.material_digest.is_none()) {
            return Err("human access stage requires exact retained material identity");
        }
        Ok(self.clone())
    }
}

impl HumanAccessMembershipObservation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn current_window(&self) -> Result<HumanAccessMembershipObservation, &'static str> {
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["HUMAN_ACCESS_EVENT_TYPE", "HUMAN_ACCESS_WORK_KIND", "HumanAccessWorkNotice", "HumanAccessHandoff", "HumanAccessMembershipObservation"];
