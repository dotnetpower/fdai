#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostTurnToolReceipt {
    pub tool_name: String,
    pub status: String,
    pub evidence_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostTurnProcedureReceipt {
    pub schema_version: String,
    pub kind: String,
    pub principal_scope: String,
    pub turn_id: String,
    pub ontology_release_digest: String,
    pub semantic_catalog_digest: String,
    pub plan_digest: String,
    pub execution_receipt_digest: String,
    pub shape_digest: String,
    pub tool_receipts: Vec<PostTurnToolReceipt>,
}

impl PostTurnProcedureReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.kind.as_str(), "verified_ontology_query_shape") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostTurnReviewInputWire {
    pub review_id: String,
    pub principal_scope: String,
    pub operator_turn_id: String,
    pub assistant_turn_id: String,
    pub completed_at: String,
    pub operator_body: Option<String>,
    pub assistant_body: Option<String>,
    pub tool_receipts: Vec<PostTurnToolReceipt>,
    pub validation_outcomes: Vec<String>,
    pub explicit_corrections: Vec<String>,
    pub evidence_refs: Vec<String>,
    pub memory_scope_kind: Option<String>,
    pub memory_scope_ref: Option<String>,
    pub failure_recovered: bool,
    pub procedure_fingerprint: Option<String>,
    pub repeated_procedure_count: i64,
    #[allow(clippy::type_complexity)]
    pub procedure_receipt: Option<Box<PostTurnProcedureReceipt>>,
}

impl PostTurnReviewInputWire {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(0_i64..=9223372036854775807_i64).contains(&self.repeated_procedure_count) { return Err("repeated_procedure_count out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostTurnBodyConsent {
    pub share_with_learner: bool,
    pub principal_scope: String,
    pub consent_ref: String,
}

impl PostTurnBodyConsent {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !self.share_with_learner { return Err("share_with_learner violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BragiPostTurnReviewEnvelope {
    pub producer_principal: String,
    pub kind: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub review: Box<PostTurnReviewInputWire>,
    #[allow(clippy::type_complexity)]
    pub body_consent: Option<Box<PostTurnBodyConsent>>,
}

impl BragiPostTurnReviewEnvelope {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.producer_principal.as_str(), "Bragi") { return Err("invalid producer_principal literal"); }
        if !matches!(self.kind.as_str(), "post_turn_review") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatorPostTurnReviewRequestEnvelope {
    pub kind: String,
    pub idempotency_key: String,
    pub review: Box<PostTurnReviewInputWire>,
}

impl OperatorPostTurnReviewRequestEnvelope {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "post_turn_review_request") { return Err("invalid kind literal"); }
        Ok(())
    }
}

pub const POST_TURN_REVIEW_TOPIC: &str = "object.post-turn-review";
pub const POST_TURN_REVIEW_REQUEST_TOPIC: &str = "operator.post-turn-review.requests";
pub const POST_TURN_REVIEW_REQUEST_CONSUMER_GROUP: &str = "core-post-turn-review-v1";
pub const POST_TURN_REVIEW_KIND: &str = "post_turn_review";
pub const POST_TURN_REVIEW_PRODUCER: &str = "Bragi";
impl PostTurnProcedureReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn procedure_fingerprint(&self) -> String {
        core::hint::black_box(String::new())
    }
}

impl PostTurnReviewInputWire {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn scope_and_repetition_are_bound(&self) -> Result<PostTurnReviewInputWire, &'static str> {
        if (self.memory_scope_kind.is_none()) != (self.memory_scope_ref.is_none()) {
            return Err("memory scope kind and ref MUST be supplied together");
        }
        if (self.procedure_fingerprint.is_none()) && ((self.repeated_procedure_count) != 0) {
            return Err("repeated procedure count requires a fingerprint");
        }
        Ok(self.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_wire_mapping(&self) -> std::collections::BTreeMap<String, String> {
        let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("review_id"), self.review_id.clone()), (String::from("principal_scope"), self.principal_scope.clone()), (String::from("operator_turn_id"), self.operator_turn_id.clone()), (String::from("assistant_turn_id"), self.assistant_turn_id.clone()), (String::from("completed_at"), String::new()), (String::from("operator_body"), (self.operator_body.clone()).unwrap_or_default()), (String::from("assistant_body"), (self.assistant_body.clone()).unwrap_or_default()), (String::from("tool_receipts"), String::new()), (String::from("validation_outcomes"), String::new()), (String::from("explicit_corrections"), String::new()), (String::from("evidence_refs"), String::new()), (String::from("memory_scope_kind"), (self.memory_scope_kind.clone()).unwrap_or_default()), (String::from("memory_scope_ref"), (self.memory_scope_ref.clone()).unwrap_or_default()), (String::from("failure_recovered"), String::new()), (String::from("procedure_fingerprint"), (self.procedure_fingerprint.clone()).unwrap_or_default()), (String::from("repeated_procedure_count"), String::new())]);
        result.clone()
    }
}

impl BragiPostTurnReviewEnvelope {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_wire_mapping(&self) -> std::collections::BTreeMap<String, String> {
        let mut payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("producer_principal"), self.producer_principal.clone()), (String::from("kind"), self.kind.clone()), (String::from("correlation_id"), self.correlation_id.clone()), (String::from("idempotency_key"), self.idempotency_key.clone()), (String::from("review"), String::new())]);
        payload.clone()
    }
}

impl OperatorPostTurnReviewRequestEnvelope {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn request_id(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_wire_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("kind"), self.kind.clone()), (String::from("idempotency_key"), self.idempotency_key.clone()), (String::from("review"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn post_turn_review_event_payload(mut review: PostTurnReviewInputWire, mut body_consent: Option<PostTurnBodyConsent>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn post_turn_review_request_payload(mut review: PostTurnReviewInputWire) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["BragiPostTurnReviewEnvelope", "OperatorPostTurnReviewRequestEnvelope", "POST_TURN_REVIEW_REQUEST_CONSUMER_GROUP", "POST_TURN_REVIEW_REQUEST_TOPIC", "POST_TURN_REVIEW_KIND", "POST_TURN_REVIEW_PRODUCER", "POST_TURN_REVIEW_TOPIC", "PostTurnBodyConsent", "PostTurnProcedureReceipt", "PostTurnReviewInputWire", "PostTurnToolReceipt", "post_turn_review_event_payload", "post_turn_review_request_payload"];
