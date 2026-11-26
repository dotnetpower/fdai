#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertRollbackBaseline {
    pub rule: String,
    pub processing_rule: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertTreatment {
    pub kind: String,
    pub target_ref: String,
    pub replacement_group_ref: Option<String>,
    pub remove_group_ref: Option<String>,
    pub processing_rule_ref: Option<String>,
    pub starts_at: Option<String>,
    pub ends_at: Option<String>,
    pub evaluation: Option<String>,
}

impl AlertTreatment {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "routing" | "suppression" | "evaluation") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertChangePlan {
    pub schema_version: String,
    pub action_type: String,
    pub tenant_ref: String,
    pub scope_ref: String,
    pub requester_ref: String,
    pub evidence_digest: String,
    pub policy_digest: String,
    pub target_revision: String,
    pub treatment: Box<AlertTreatment>,
    pub service_refs: Vec<String>,
    pub lock_refs: Vec<String>,
    pub created_at: String,
    pub expires_at: String,
    pub max_execution_seconds: String,
    pub max_observation_seconds: String,
    pub max_recovery_seconds: String,
    pub rollback_ref: String,
    pub evaluation_receipt_digest: Option<String>,
    pub execution_path: String,
    pub default_mode: String,
    pub quorum_required: i64,
    pub execution_authority: String,
}

impl AlertChangePlan {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.1.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.action_type.as_str(), "ops.update-alert-routing" | "ops.set-alert-notification-window" | "ops.tune-alert-evaluation" | "ops.restore-alert-configuration") { return Err("invalid action_type literal"); }
        if !matches!(self.execution_path.as_str(), "direct_api") { return Err("invalid execution_path literal"); }
        if !matches!(self.default_mode.as_str(), "shadow") { return Err("invalid default_mode literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertApproval {
    pub plan_digest: String,
    pub principal_ref: String,
    pub tenant_ref: String,
    pub scope_ref: String,
    pub decision: String,
    pub lane: String,
    pub service_refs: Vec<String>,
    pub decided_at: String,
    pub expires_at: String,
    pub receipt_ref: String,
    pub authority_revision: String,
}

impl AlertApproval {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.decision.as_str(), "approved" | "rejected") { return Err("invalid decision literal"); }
        if !matches!(self.lane.as_str(), "service_owner" | "change_owner") { return Err("invalid lane literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertDispatchEvidence {
    pub plan_digest: String,
    pub evidence_digest: String,
    pub policy_digest: String,
    pub target_revision: String,
    pub evaluated_at: String,
    pub valid_until: String,
    pub authorization_until: Option<String>,
    pub executor_ref: String,
    pub dry_run_digest: String,
    pub promotion_digest: Option<String>,
    pub writer_fence_ref: Option<String>,
    pub audit_intent_ref: Option<String>,
    pub recovery_admission_ref: Option<String>,
    pub dependencies_current: String,
    pub actors_current: String,
    pub observer_ready: String,
    pub recovery_ready: String,
    pub kill_switch: String,
    pub mode: String,
    pub synthetic: String,
}

impl AlertDispatchEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.mode.as_str(), "shadow" | "enforce") { return Err("invalid mode literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertEffectObservation {
    pub plan_digest: String,
    pub dispatch_ref: String,
    pub source_ref: String,
    pub observer_ref: String,
    pub executor_ref: String,
    pub window_start: String,
    pub window_end: String,
    pub recorded_at: String,
    pub coverage: String,
    pub configuration_matches: String,
    pub collection_continues: String,
    pub protected_paths_preserved: String,
    pub response_deadlines_preserved: String,
    pub expected_delivery_observed: String,
    pub eligible_events: String,
    pub failures: String,
    pub missed_incidents: String,
    pub synthetic: String,
    pub receipt_ref: String,
    pub recovery: String,
    pub execution_authority: String,
}

impl AlertEffectObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.coverage.as_str(), "complete" | "partial" | "unavailable") { return Err("invalid coverage literal"); }
        Ok(())
    }
}

impl AlertTreatment {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn single_axis(&self) -> Result<String, &'static str> {
        let routing: bool = (self.replacement_group_ref.is_some()) && (self.remove_group_ref.is_some());
        let scheduling: bool = (self.starts_at.is_some()) && (self.ends_at.is_some());
        let any_routing: bool = (self.replacement_group_ref.is_some()) || (self.remove_group_ref.is_some());
        let any_scheduling: bool = (self.starts_at.is_some()) || (self.ends_at.is_some());
        if (self.kind.clone()) == (String::from("routing")) {
            if (self.remove_group_ref.clone()) == Some((self.replacement_group_ref.clone()).unwrap_or_default()) {
                return Err("replacement group MUST differ from removed group");
            }
        } else if (self.kind.clone()) == (String::from("suppression")) {
            if (!(scheduling)) || ((!((self.processing_rule_ref.clone()).is_some())) || ((any_routing) || ((self.evaluation.clone()).is_some()))) {
                return Err("suppression MUST name a pre-provisioned rule and finite window");
            }
            if (self.starts_at.is_some()) && (self.ends_at.is_some()) {
                if ((self.starts_at.clone()).unwrap_or_default()) >= ((self.ends_at.clone()).unwrap_or_default()) {
                    return Err("suppression interval MUST be positive");
                }
            }
        }
        Ok(String::new())
    }
}

impl AlertChangePlan {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bindings(&self) -> Result<String, &'static str> {
        if (self.expires_at.clone()) <= (self.created_at.clone()) {
            return Err("plan validity MUST be positive");
        }
        Ok(String::new())
    }
}

impl AlertApproval {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn decision_interval(&self) -> Result<String, &'static str> {
        if ((self.expires_at.clone()) <= (self.decided_at.clone())) || (((((self.service_refs.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.service_refs.clone()).len() as i64))) {
            return Err("approval interval and service identities MUST be unambiguous");
        }
        Ok(String::new())
    }
}

impl AlertEffectObservation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn time_and_identity(&self) -> Result<String, &'static str> {
        if !(((self.window_start.clone()) < (self.window_end.clone())) && ((self.window_end.clone()) <= (self.recorded_at.clone()))) {
            return Err("effect observation window MUST be positive and complete");
        }
        if (((std::collections::BTreeSet::from([self.source_ref.clone(), self.observer_ref.clone(), self.executor_ref.clone()])).len() as i64)) != (3_i64) {
            return Err("effect source observer and executor MUST be distinct");
        }
        Ok(String::new())
    }
}

