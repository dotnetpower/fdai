use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WaraApplicabilityStatus {
    #[default]
    Applicable,
    NotApplicable,
    Unknown,
}

impl WaraApplicabilityStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Applicable => "applicable",
            Self::NotApplicable => "not_applicable",
            Self::Unknown => "unknown",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WaraEvaluationStatus {
    #[default]
    Evaluated,
    NotEvaluated,
    Blocked,
}

impl WaraEvaluationStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Evaluated => "evaluated",
            Self::NotEvaluated => "not_evaluated",
            Self::Blocked => "blocked",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WaraSatisfactionStatus {
    #[default]
    Satisfied,
    Failed,
    NotApplicable,
    Unknown,
}

impl WaraSatisfactionStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Satisfied => "satisfied",
            Self::Failed => "failed",
            Self::NotApplicable => "not_applicable",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraScopedResource {
    pub resource_id: String,
    pub provider_resource_type: String,
    pub workload_tags: Vec<String>,
}

impl WaraScopedResource {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.resource_id.trim().is_empty() { return Err("resource_id must be non-empty"); }
        if self.provider_resource_type.trim().is_empty() { return Err("provider_resource_type must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraEvidenceReceipt {
    pub recommendation_id: String,
    pub evidence_ref: String,
    pub evidence_kind: String,
    pub producer: String,
    pub scope_digest: String,
    pub source_revision: String,
    pub inventory_generation: String,
    pub observed_at: String,
    pub recorded_at: String,
    pub evidence_digest: String,
    pub freshness_ceiling_seconds: i64,
    pub complete: bool,
    pub truncated: bool,
    pub conflicting: bool,
    pub synthetic: bool,
    pub provider_error: Option<String>,
    pub outcome: WaraSatisfactionStatus,
    pub applicability_approval_ref: Option<String>,
}

impl WaraEvidenceReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.recommendation_id.trim().is_empty() { return Err("recommendation_id must be non-empty"); }
        if self.evidence_ref.trim().is_empty() { return Err("evidence_ref must be non-empty"); }
        if self.evidence_kind.trim().is_empty() { return Err("evidence_kind must be non-empty"); }
        if self.producer.trim().is_empty() { return Err("producer must be non-empty"); }
        if self.scope_digest.trim().is_empty() { return Err("scope_digest must be non-empty"); }
        if self.source_revision.trim().is_empty() { return Err("source_revision must be non-empty"); }
        if self.inventory_generation.trim().is_empty() { return Err("inventory_generation must be non-empty"); }
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.recorded_at.trim().is_empty() { return Err("recorded_at must be non-empty"); }
        if self.evidence_digest.trim().is_empty() { return Err("evidence_digest must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraAssessmentRequest {
    pub assessment_id: String,
    pub framework_revision: String,
    pub crosswalk_digest: String,
    pub ontology_release: String,
    pub inventory_generation: String,
    pub workload_id: String,
    pub resources: Vec<WaraScopedResource>,
    pub evaluated_at: String,
    pub recorded_at: String,
    pub evaluator_bindings_digest: Option<String>,
    pub evidence: Vec<WaraEvidenceReceipt>,
    pub rule_bindings_digest: Option<String>,
    pub enablement_profile: Option<String>,
}

impl WaraAssessmentRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.assessment_id.trim().is_empty() { return Err("assessment_id must be non-empty"); }
        if self.framework_revision.trim().is_empty() { return Err("framework_revision must be non-empty"); }
        if self.crosswalk_digest.trim().is_empty() { return Err("crosswalk_digest must be non-empty"); }
        if self.ontology_release.trim().is_empty() { return Err("ontology_release must be non-empty"); }
        if self.inventory_generation.trim().is_empty() { return Err("inventory_generation must be non-empty"); }
        if self.workload_id.trim().is_empty() { return Err("workload_id must be non-empty"); }
        if self.evaluated_at.trim().is_empty() { return Err("evaluated_at must be non-empty"); }
        if self.recorded_at.trim().is_empty() { return Err("recorded_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraControlResult {
    pub recommendation_id: String,
    pub catalog_state: String,
    pub mapping_state: String,
    pub applicability: WaraApplicabilityStatus,
    pub evaluation: WaraEvaluationStatus,
    pub satisfaction: WaraSatisfactionStatus,
    pub evidence_refs: Vec<String>,
    pub evidence_digests: Vec<String>,
    pub evidence_complete: bool,
    pub limitations: Vec<String>,
    pub enablement: Option<String>,
}

impl WaraControlResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.recommendation_id.trim().is_empty() { return Err("recommendation_id must be non-empty"); }
        if self.catalog_state.trim().is_empty() { return Err("catalog_state must be non-empty"); }
        if self.mapping_state.trim().is_empty() { return Err("mapping_state must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WaraAssessmentResult {
    pub assessment_id: String,
    pub mode: String,
    pub execution_authority: bool,
    pub framework_revision: String,
    pub crosswalk_digest: String,
    pub evaluator_bindings_digest: Option<String>,
    pub ontology_release: String,
    pub inventory_generation: String,
    pub workload_id: String,
    pub scope_digest: String,
    pub evaluated_at: String,
    pub recorded_at: String,
    pub controls: Vec<WaraControlResult>,
    pub aggregate_counts: BTreeMap<String, i64>,
    pub result_digest: String,
    pub rule_bindings_digest: Option<String>,
    pub enablement_profile: Option<String>,
}

impl WaraAssessmentResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.assessment_id.trim().is_empty() { return Err("assessment_id must be non-empty"); }
        if self.mode.trim().is_empty() { return Err("mode must be non-empty"); }
        if self.framework_revision.trim().is_empty() { return Err("framework_revision must be non-empty"); }
        if self.crosswalk_digest.trim().is_empty() { return Err("crosswalk_digest must be non-empty"); }
        if self.ontology_release.trim().is_empty() { return Err("ontology_release must be non-empty"); }
        if self.inventory_generation.trim().is_empty() { return Err("inventory_generation must be non-empty"); }
        if self.workload_id.trim().is_empty() { return Err("workload_id must be non-empty"); }
        if self.scope_digest.trim().is_empty() { return Err("scope_digest must be non-empty"); }
        if self.evaluated_at.trim().is_empty() { return Err("evaluated_at must be non-empty"); }
        if self.recorded_at.trim().is_empty() { return Err("recorded_at must be non-empty"); }
        if self.result_digest.trim().is_empty() { return Err("result_digest must be non-empty"); }
        Ok(())
    }
}

impl WaraAssessmentRequest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn scope_digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

impl WaraControlResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        let mut value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("recommendation_id"), self.recommendation_id.clone()), (String::from("catalog_state"), self.catalog_state.clone()), (String::from("mapping_state"), self.mapping_state.clone()), (String::from("applicability"), String::new()), (String::from("evaluation"), String::new()), (String::from("satisfaction"), String::new()), (String::from("evidence_refs"), String::new()), (String::from("evidence_digests"), String::new()), (String::from("evidence_complete"), String::new()), (String::from("limitations"), String::new())]);
        value.clone()
    }
}

impl WaraAssessmentResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self, mut include_digest: bool) -> std::collections::BTreeMap<String, String> {
        let mut value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("assessment_id"), self.assessment_id.clone()), (String::from("mode"), self.mode.clone()), (String::from("execution_authority"), String::new()), (String::from("framework_revision"), self.framework_revision.clone()), (String::from("crosswalk_digest"), self.crosswalk_digest.clone()), (String::from("ontology_release"), self.ontology_release.clone()), (String::from("inventory_generation"), self.inventory_generation.clone()), (String::from("workload_id"), self.workload_id.clone()), (String::from("scope_digest"), self.scope_digest.clone()), (String::from("evaluated_at"), String::new()), (String::from("recorded_at"), String::new()), (String::from("controls"), String::new()), (String::from("aggregate_counts"), String::new())]);
        if self.evaluator_bindings_digest.is_some() {
            value.insert(String::from("evaluator_bindings_digest"), (self.evaluator_bindings_digest.clone()).unwrap_or_default());
        }
        if self.rule_bindings_digest.is_some() {
            value.insert(String::from("rule_bindings_digest"), (self.rule_bindings_digest.clone()).unwrap_or_default());
        }
        if include_digest {
            value.insert(String::from("result_digest"), self.result_digest.clone());
        }
        value.clone()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["WaraApplicabilityStatus", "WaraAssessmentRequest", "WaraAssessmentResult", "WaraControlResult", "WaraEvaluationStatus", "WaraEvidenceReceipt", "WaraSatisfactionStatus", "WaraScopedResource"];
