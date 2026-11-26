use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentRevocationRequest {
    pub case_id: String,
    pub revision: i64,
    pub replacement_revisions: BTreeMap<String, i64>,
}

impl AssignmentRevocationRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=9223372036854775807_i64).contains(&self.revision) { return Err("revision out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentRequestNotice {
    pub schema_version: String,
    pub proposal_ref: String,
    pub proposal_id: String,
    pub case_id: String,
    pub proposal_digest: String,
    pub operation: String,
    pub accepted_at: String,
    pub producer_service: String,
    pub execution_authority: bool,
    pub approval_authority: bool,
    pub mutation_authority: bool,
}

impl AssignmentRequestNotice {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0" | "1.1.0" | "1.2.0" | "1.3.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.operation.as_str(), "assignments.create" | "assignments.submit" | "assignments.confirm" | "assignments.review") { return Err("invalid operation literal"); }
        if !matches!(self.producer_service.as_str(), "operator-service") { return Err("invalid producer_service literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.approval_authority { return Err("approval_authority violated literal bool invariant"); }
        if self.mutation_authority { return Err("mutation_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentIntakeProjection {
    pub schema_version: String,
    pub proposal_id: String,
    pub proposal_digest: String,
    pub status: String,
    pub reason: String,
    pub observed_at: String,
    pub execution_authority: bool,
    pub approval_authority: bool,
    pub mutation_authority: bool,
}

impl AssignmentIntakeProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.status.as_str(), "awaiting_agent_review" | "held") { return Err("invalid status literal"); }
        if !matches!(self.reason.as_str(), "verified_operator_receipt" | "operator_receipt_unavailable" | "operator_receipt_mismatch" | "operator_receipt_expired" | "operator_receipt_unauthorized") { return Err("invalid reason literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.approval_authority { return Err("approval_authority violated literal bool invariant"); }
        if self.mutation_authority { return Err("mutation_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentCaseResult {
    pub schema_version: Option<String>,
    pub proposal_id: String,
    pub request_digest: String,
    pub operator_case_id: String,
    pub case_id: String,
    pub state: String,
    pub revision: i64,
    pub ownership_effect_ref: Option<String>,
    pub iam_effect_ref: Option<String>,
    pub execution_authority: bool,
}

impl AssignmentCaseResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.state.as_str(), "draft" | "pending_review" | "approved" | "ownership_pr_open" | "ownership_merged" | "iam_applying" | "iam_revoked" | "active" | "revoked" | "rejected" | "degraded" | "superseded" | "pending_confirmation" | "pending_owner_review" | "activation_pending" | "conflict") { return Err("invalid state literal"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.revision) { return Err("revision out of bounds"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentAgentDecision {
    pub notice: Box<AssignmentRequestNotice>,
    pub disposition: String,
    pub reason: String,
    #[allow(clippy::type_complexity)]
    pub result: Option<Box<AssignmentCaseResult>>,
    pub execution_authority: bool,
}

impl AssignmentAgentDecision {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.disposition.as_str(), "validated" | "reviewed" | "held" | "materialized") { return Err("invalid disposition literal"); }
        if !matches!(self.reason.as_str(), "command_validated" | "human_confirmation_verified" | "independent_review_verified" | "case_materialized" | "command_held" | "review_held" | "materialization_held" | "agent_binding_unavailable") { return Err("invalid reason literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const ASSIGNMENT_REQUEST_TOPIC: &str = "operator.human-assignment.requests";
pub const ASSIGNMENT_PROJECTION_TOPIC: &str = "core.human-assignment.projections";
pub const ASSIGNMENT_CONSUMER_GROUP: &str = "core-human-assignment-v1";
pub const ASSIGNMENT_EVENT_TYPE: &str = "human.assignment.requested";
pub const DIGEST: &str = "^[a-f0-9]{64}$";
pub const REFERENCE: &str = "^operator-proposal:iam:[a-f0-9]{64}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NoAuthorityRecord {
    pub initialized: bool,
}

impl NoAuthorityRecord {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn explicit_values(mut value: String, mut info: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
}

impl AssignmentRevocationRequest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_references(&self) -> Result<AssignmentRevocationRequest, &'static str> {
        Err("runtime_binding_required")
    }
}

impl AssignmentRequestNotice {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_identity(&self) -> Result<AssignmentRequestNotice, &'static str> {
        if ((self.operation.clone()) == (String::from("assignments.create"))) && ((self.case_id.clone()) != (self.proposal_id.clone())) {
            return Err("assignment creation case identity MUST match its proposal");
        }
        Ok(self.clone())
    }
}

impl AssignmentIntakeProjection {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn consistent_disposition(&self) -> Result<AssignmentIntakeProjection, &'static str> {
        if ((self.status.clone()) == (String::from("awaiting_agent_review"))) != ((self.reason.clone()) == (String::from("verified_operator_receipt"))) {
            return Err("assignment intake status does not match its evidence");
        }
        Ok(self.clone())
    }
}

impl AssignmentCaseResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn verified_state(&self) -> Result<AssignmentCaseResult, &'static str> {
        if ((self.schema_version.clone()) != Some(String::from("1.3.0"))) && ((matches!(self.state.as_str(), "active" | "revoked")) && (!(((self.ownership_effect_ref.clone()).is_some()) && ((self.iam_effect_ref.clone()).is_some())))) {
            return Err("converged assignment result requires both effect references");
        }
        if ((self.state.clone()) == (String::from("iam_revoked"))) && (!((self.iam_effect_ref.clone()).is_some())) {
            return Err("IAM removal observation requires an independent effect reference");
        }
        if (matches!(self.state.as_str(), "iam_revoked" | "revoked")) && ((self.schema_version.clone()) != Some(String::from("1.1.0"))) {
            return Err("revocation observations require contract version 1.1.0");
        }
        if (self.schema_version.clone()) == Some(String::from("1.2.0")) {
            if (self.iam_effect_ref.is_some()) || (!(matches!(self.state.as_str(), "draft" | "pending_review" | "approved" | "ownership_pr_open" | "ownership_merged" | "rejected"))) {
                return Err("scoped duty result MUST NOT represent an IAM lifecycle");
            }
            if ((self.state.clone()) == (String::from("ownership_merged"))) && (!((self.ownership_effect_ref.clone()).is_some())) {
                return Err("scoped duty ownership requires its independent merge reference");
            }
        }
        if (self.schema_version.clone()) == Some(String::from("1.3.0")) {
            if (self.ownership_effect_ref.is_some()) || (self.iam_effect_ref.is_some()) {
                return Err("reporting-line result cannot represent an ownership or IAM effect");
            }
            if !(matches!(self.state.as_str(), "pending_confirmation" | "pending_owner_review" | "activation_pending" | "active" | "conflict" | "rejected" | "superseded")) {
                return Err("reporting-line result uses an unrelated assignment state");
            }
        }
        Ok(self.clone())
    }
}

impl AssignmentAgentDecision {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn consistent(&self) -> Result<AssignmentAgentDecision, &'static str> {
        let required_reason: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("validated"), String::from("command_validated")), (String::from("materialized"), String::from("case_materialized"))]);
        if (self.disposition.clone()) == (String::from("reviewed")) {
            let expected_review_reason: String = String::from("human_confirmation_verified\" if self.notice.schema_version == \"1.3.0\" and self.notice.operation == \"assignments.confirm\" else \"independent_review_verified");
            if (self.reason.clone()) != (expected_review_reason.clone()) {
                return Err("assignment review reason does not match its command");
            }
        }
        if ((self.disposition.clone()) == (String::from("materialized"))) != (self.result.is_some()) {
            return Err("only a materialized assignment may carry a case result");
        }
        Ok(self.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn assignment_content_digest(mut value: std::collections::BTreeMap<String, String>) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ASSIGNMENT_CONSUMER_GROUP", "ASSIGNMENT_EVENT_TYPE", "ASSIGNMENT_PROJECTION_TOPIC", "ASSIGNMENT_REQUEST_TOPIC", "AssignmentIntakeReason", "AssignmentIntakeProjection", "AssignmentRequestNotice", "AssignmentRevocationRequest", "AssignmentAgentDecision", "AssignmentCaseResult", "assignment_content_digest"];
