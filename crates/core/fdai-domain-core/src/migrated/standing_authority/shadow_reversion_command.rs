#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExpectedAuthorizationState {
    #[default]
    Active,
    Revoked,
    Expired,
    Superseded,
}

impl ExpectedAuthorizationState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Revoked => "revoked",
            Self::Expired => "expired",
            Self::Superseded => "superseded",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ShadowReversionOutcome {
    #[default]
    Applied,
    Duplicate,
    RejectedIntentNotRecorded,
    RejectedStaleAuthorization,
    RejectedWriterFailure,
    RejectedTerminalNotRecorded,
}

impl ShadowReversionOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Applied => "applied",
            Self::Duplicate => "duplicate",
            Self::RejectedIntentNotRecorded => "rejected_intent_not_recorded",
            Self::RejectedStaleAuthorization => "rejected_stale_authorization",
            Self::RejectedWriterFailure => "rejected_writer_failure",
            Self::RejectedTerminalNotRecorded => "rejected_terminal_not_recorded",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ShadowReversionSafetyBindings {
    pub stop_condition_ref: String,
    pub rollback_plan_ref: String,
    pub kill_switch_ref: String,
    pub blast_radius_scope: String,
    pub rollback_tested: bool,
}

impl ShadowReversionSafetyBindings {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.blast_radius_scope.as_str(), "resource" | "resource_group") { return Err("invalid blast_radius_scope literal"); }
        if !self.rollback_tested { return Err("rollback_tested violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ShadowReversionCommand {
    pub source_revision_id: String,
    pub reverted_action_types: Vec<String>,
    pub finding_id: String,
    pub plan_id: String,
    pub disposition: String,
    pub required_transition: String,
    pub reason_code: String,
    pub expected_authorization: String,
    pub expected_authorization_state: ExpectedAuthorizationState,
    pub safety: Box<ShadowReversionSafetyBindings>,
    pub proposer_principal: String,
    pub reviewer_principal: String,
    pub authentication_evidence_digest: String,
    pub proposed_at: String,
    pub contract_version: String,
    pub execution_authority: bool,
    pub promotion_authority: bool,
    pub registry_mutated: bool,
    pub recovery_authority: bool,
    pub idempotency_key: String,
    pub command_id: String,
}

impl ShadowReversionCommand {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.promotion_authority { return Err("promotion_authority violated literal bool invariant"); }
        if self.registry_mutated { return Err("registry_mutated violated literal bool invariant"); }
        if self.recovery_authority { return Err("recovery_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ShadowReversionIntent {
    pub command_id: String,
    pub idempotency_key: String,
    pub expected_authorization: String,
    pub recorded_at: String,
    pub intent_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ShadowReversionTerminal {
    pub command_id: String,
    pub idempotency_key: String,
    pub intent_digest: String,
    pub outcome: ShadowReversionOutcome,
    pub detail: String,
    pub recorded_at: String,
    pub execution_authority: bool,
    pub promotion_authority: bool,
    pub terminal_audit_digest: String,
}

impl ShadowReversionTerminal {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.promotion_authority { return Err("promotion_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const SHADOW_REVERSION_CONTRACT_VERSION: &str = "a3e-shadow-reversion-v1";
pub const REVISION: &str = "^(?:[0-9a-f]{40}|[0-9a-f]{64})$";
pub const ACTION_TYPE_ID: &str = "^[a-z][a-z0-9.-]{0,63}@\\d+\\.\\d+\\.\\d+$";
pub const BINDING_REF: &str = "^[a-z][a-z0-9-]{0,31}:[A-Za-z0-9._/-]{1,128}$";
impl ShadowReversionSafetyBindings {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn as_body(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("stop_condition_ref"), self.stop_condition_ref.clone()), (String::from("rollback_plan_ref"), self.rollback_plan_ref.clone()), (String::from("kill_switch_ref"), self.kill_switch_ref.clone()), (String::from("blast_radius_scope"), self.blast_radius_scope.clone()), (String::from("rollback_tested"), String::new())])
    }
}

impl ShadowReversionCommand {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn audit_body(&self) -> std::collections::BTreeMap<String, String> {
        let mut body: std::collections::BTreeMap<String, String> = command_body(self.clone());
        body.insert(String::from("idempotency_key"), self.idempotency_key.clone());
        body.insert(String::from("command_id"), self.command_id.clone());
        body.clone()
    }
}

pub trait ShadowReversionWriter {
    fn record_intent(&self, intent: ShadowReversionIntent) -> bool;
    fn current_fence_matches(&self, fence: String) -> bool;
    fn apply(&self, command: ShadowReversionCommand, intent: ShadowReversionIntent) -> bool;
    fn record_terminal(&self, terminal: ShadowReversionTerminal) -> bool;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_distinct_human(mut name: String, mut principal: String) -> Result<(), &'static str> {
    if ((principal.clone()).starts_with("agent:")) || ((principal.clone()).starts_with("identity:thor")) {
        return Err("name MUST be human not agentexecutor");
    }
    if !((principal.clone()).starts_with("human:")) {
        return Err("name MUST start with human:");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn apply_shadow_reversion(mut command: ShadowReversionCommand, mut writer: String, mut recorded_at: String) -> ShadowReversionTerminal {
    let intent: ShadowReversionIntent = ShadowReversionIntent { command_id: command.command_id.clone(), idempotency_key: command.idempotency_key.clone(), expected_authorization: command.expected_authorization.clone(), recorded_at: recorded_at.clone(), ..Default::default() };
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::too_many_arguments)]
pub fn build_shadow_reversion_command(mut plan: String, mut source_revision_id: String, mut reverted_action_types: Vec<String>, mut expected_authorization: String, mut expected_authorization_state: ExpectedAuthorizationState, mut safety: ShadowReversionSafetyBindings, mut proposer_principal: String, mut reviewer_principal: String, mut authentication_evidence_digest: String, mut proposed_at: String) -> Result<ShadowReversionCommand, &'static str> {
    Ok(ShadowReversionCommand { source_revision_id: source_revision_id.clone(), reverted_action_types: ((reverted_action_types.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>(), expected_authorization: expected_authorization.clone(), expected_authorization_state: expected_authorization_state.clone(), safety: Box::new(safety.clone()), proposer_principal: proposer_principal.clone(), reviewer_principal: reviewer_principal.clone(), authentication_evidence_digest: authentication_evidence_digest.clone(), proposed_at: proposed_at.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn fence_body(mut fence: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("family_id"), String::new()), (String::from("revision_id"), String::new()), (String::from("fencing_generation"), String::new()), (String::from("transition_digest"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn idempotency_key(mut command: ShadowReversionCommand) -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn command_body(mut command: ShadowReversionCommand) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("contract_version"), String::from(SHADOW_REVERSION_CONTRACT_VERSION)), (String::from("source_revision_id"), command.source_revision_id.clone()), (String::from("reverted_action_types"), String::new()), (String::from("finding_id"), command.finding_id.clone()), (String::from("plan_id"), command.plan_id.clone()), (String::from("disposition"), String::new()), (String::from("required_transition"), String::new()), (String::from("reason_code"), command.reason_code.clone()), (String::from("expected_authorization"), String::new()), (String::from("expected_authorization_state"), String::new()), (String::from("safety"), String::new()), (String::from("proposer_principal"), command.proposer_principal.clone()), (String::from("reviewer_principal"), command.reviewer_principal.clone()), (String::from("authentication_evidence_digest"), command.authentication_evidence_digest.clone()), (String::from("proposed_at"), String::new()), (String::from("execution_authority"), String::new()), (String::from("promotion_authority"), String::new()), (String::from("registry_mutated"), String::new()), (String::from("recovery_authority"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["REVERTIBLE_DISPOSITIONS", "SHADOW_REVERSION_CONTRACT_VERSION", "ExpectedAuthorizationState", "ShadowReversionCommand", "ShadowReversionIntent", "ShadowReversionOutcome", "ShadowReversionSafetyBindings", "ShadowReversionTerminal", "ShadowReversionWriter", "apply_shadow_reversion", "build_shadow_reversion_command"];
