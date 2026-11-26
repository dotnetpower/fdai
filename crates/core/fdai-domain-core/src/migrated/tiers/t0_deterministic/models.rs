use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PipelineStage {
    #[default]
    L1Evaluate,
    L1Simulate,
    Abstain,
}

impl PipelineStage {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::L1Evaluate => "L1_evaluate",
            Self::L1Simulate => "L1_simulate",
            Self::Abstain => "abstain",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RegoEvaluationReceipt {
    pub decision_path: String,
    pub opa_version: String,
    pub parser_id: String,
    pub parser_version: String,
    pub policy_source_digest: String,
    pub normalized_semantic_digest: String,
    pub input_evidence_digest: String,
    pub denied: bool,
    pub result_digest: String,
}

impl RegoEvaluationReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.decision_path.trim().is_empty() { return Err("decision_path must be non-empty"); }
        if self.opa_version.trim().is_empty() { return Err("opa_version must be non-empty"); }
        if self.parser_id.trim().is_empty() { return Err("parser_id must be non-empty"); }
        if self.parser_version.trim().is_empty() { return Err("parser_version must be non-empty"); }
        if self.policy_source_digest.trim().is_empty() { return Err("policy_source_digest must be non-empty"); }
        if self.normalized_semantic_digest.trim().is_empty() { return Err("normalized_semantic_digest must be non-empty"); }
        if self.input_evidence_digest.trim().is_empty() { return Err("input_evidence_digest must be non-empty"); }
        if self.result_digest.trim().is_empty() { return Err("result_digest must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Finding {
    pub finding_id: String,
    pub rule_id: String,
    pub rule_version: String,
    pub resource_id: String,
    pub signal_id: String,
    pub severity: String,
    pub context: BTreeMap<String, String>,
    pub created_at: Option<String>,
    #[allow(clippy::type_complexity)]
    pub evaluation_receipt: Option<Box<RegoEvaluationReceipt>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuditHint {
    pub event_id: String,
    pub pipeline_stage: PipelineStage,
    pub tier: String,
    pub mode: String,
    pub citing_rule_ids: Vec<String>,
    pub abstained_rule_ids: Vec<String>,
    pub evaluation_receipts: Vec<RegoEvaluationReceipt>,
    pub reason: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Verdict {
    pub findings: Vec<Finding>,
    #[allow(clippy::type_complexity)]
    pub audit_hint: Option<Box<AuditHint>>,
}

impl Verdict {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn matched(&self) -> bool {
        !(self.findings.clone()).is_empty()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AuditHint", "Finding", "PipelineStage", "RegoEvaluationReceipt", "Verdict"];
