#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReconciliationOutboxDeliveryState {
    #[default]
    Pending,
    Claimed,
    Published,
}

impl ReconciliationOutboxDeliveryState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Claimed => "claimed",
            Self::Published => "published",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReconciliationTargetRevision {
    pub object_id: String,
    pub type_ref: String,
    pub revision: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EffectReconciliationRequestEvent {
    pub schema_version: String,
    pub event_type: String,
    pub reconciliation_id: String,
    pub observation_attempt_id: String,
    pub correlation_id: String,
    pub ontology_release_ref: String,
    pub action_type_ref: String,
    pub plan_digest: String,
    pub target_revisions: Vec<ReconciliationTargetRevision>,
    pub evidence: String,
    pub observation_context: String,
    pub deadline: String,
    pub evaluated_at: String,
    pub event_digest: String,
}

impl EffectReconciliationRequestEvent {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.event_type.as_str(), "ontology.effect_reconciliation.requested.v1") { return Err("invalid event_type literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EffectReconciliationResultEvent {
    pub schema_version: String,
    pub event_type: String,
    pub reconciliation_id: String,
    pub observation_attempt_id: String,
    pub correlation_id: String,
    pub ontology_release_ref: String,
    pub action_type_ref: String,
    pub plan_digest: String,
    pub target_revisions: Vec<ReconciliationTargetRevision>,
    pub observer_identity: String,
    pub executor_identity: String,
    pub source_identity: String,
    pub source_credential_lineage: String,
    pub request_digest: String,
    pub receipt_digest: String,
    pub observation_context_digest: String,
    pub verification_receipt_digest: String,
    pub recommendation_idempotency_key: String,
    pub status: String,
    pub terminal: bool,
    pub result_digest: String,
}

impl EffectReconciliationResultEvent {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.event_type.as_str(), "ontology.effect_reconciliation.result.v1") { return Err("invalid event_type literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReconciliationOutboxEvent {
    pub schema_version: String,
    pub event_type: String,
    pub idempotency_key: String,
    pub result: Box<EffectReconciliationResultEvent>,
    pub recommendation: String,
    pub proposal_only: bool,
    pub grants_authority: bool,
}

impl ReconciliationOutboxEvent {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.event_type.as_str(), "ontology.effect_reconciliation.outbox.v1") { return Err("invalid event_type literal"); }
        if !self.proposal_only { return Err("proposal_only violated literal bool invariant"); }
        if self.grants_authority { return Err("grants_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReconciliationOutboxRecord {
    pub schema_version: String,
    pub event: Box<ReconciliationOutboxEvent>,
    pub state: ReconciliationOutboxDeliveryState,
    pub attempts: i64,
    pub available_at: Option<String>,
    pub claimant_id: Option<String>,
    pub lease_until: Option<String>,
    pub published_at: Option<String>,
}

pub const DIGEST_PATTERN: &str = "^sha256:[a-f0-9]{64}$";
pub const IDENTITY_PATTERN: &str = "^reconciliation:[a-f0-9]{64}$";
pub const ATTEMPT_PATTERN: &str = "^reconciliation-attempt:[a-f0-9]{64}$";
pub const RECOMMENDATION_PATTERN: &str = "^reconciliation-next-step:[a-f0-9]{64}$";
impl EffectReconciliationRequestEvent {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_request(mut request: String, mut observation_context: String) -> String {
        if request.is_empty() {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn event_is_canonical(&self) -> Result<EffectReconciliationRequestEvent, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bind(&self, mut plan: String, mut action_type: String, mut active_release: String) -> Result<String, &'static str> {
        if plan.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

impl EffectReconciliationResultEvent {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_outcome(mut outcome: String) -> String {
        if outcome.is_empty() {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn result_is_canonical(&self) -> Result<EffectReconciliationResultEvent, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ReconciliationOutboxEvent {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_outcome(mut outcome: String) -> Result<String, &'static str> {
        if outcome.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn outbox_is_bound(&self) -> Result<ReconciliationOutboxEvent, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ReconciliationOutboxRecord {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn delivery_state_is_consistent(&self) -> Result<ReconciliationOutboxRecord, &'static str> {
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["EffectReconciliationRequestEvent", "EffectReconciliationResultEvent", "ReconciliationOutboxDeliveryState", "ReconciliationOutboxEvent", "ReconciliationOutboxRecord", "ReconciliationTargetRevision"];
