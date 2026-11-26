use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FrameworkApplicabilityStatus {
    #[default]
    Applicable,
    NotApplicable,
}

impl FrameworkApplicabilityStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Applicable => "applicable",
            Self::NotApplicable => "not_applicable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FrameworkEvaluationStatus {
    #[default]
    Evaluated,
    NotEvaluated,
    Blocked,
}

impl FrameworkEvaluationStatus {
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
pub enum FrameworkSatisfactionStatus {
    #[default]
    Satisfied,
    Failed,
    NotApplicable,
    Unknown,
}

impl FrameworkSatisfactionStatus {
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
pub struct FrameworkApplicabilityDecision {
    pub control_id: String,
    pub status: FrameworkApplicabilityStatus,
    pub requested_by: String,
    pub owner_slot: String,
    pub cadence_days: i64,
    pub justification: Option<String>,
    pub approved_by: Option<String>,
    pub approved_at: Option<String>,
    pub expires_at: Option<String>,
    pub enabled: Option<bool>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FrameworkOwnerBinding {
    pub control_id: String,
    pub owner_slot: String,
    pub owner_identity: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FrameworkRuleActivationPin {
    pub generation_id: String,
    pub generation_digest: String,
    pub rule_catalog_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FrameworkRuleProvenance {
    pub activation: Box<FrameworkRuleActivationPin>,
    pub member_rule_digest: Option<String>,
    pub coverage_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FrameworkAssessmentProfile {
    pub profile_id: String,
    pub framework_id: String,
    pub framework_version: String,
    pub catalog_digest: String,
    pub scope_kind: String,
    pub scope_digest: String,
    pub ontology_release: String,
    pub applicability: Vec<FrameworkApplicabilityDecision>,
    pub owners: Vec<FrameworkOwnerBinding>,
    pub reviewed_by: String,
    pub reviewed_at: String,
    pub inventory_generation: Option<String>,
    pub hierarchy_generation: Option<String>,
    pub operating_model: Option<String>,
    pub environment_classes: Vec<String>,
    pub regulatory_context: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub rule_activation: Option<Box<FrameworkRuleActivationPin>>,
    pub profile_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FrameworkEvidenceReceipt {
    pub framework_id: String,
    pub control_id: String,
    pub requirement_id: String,
    pub evidence_ref: String,
    pub evidence_kind: String,
    pub producer: String,
    pub source_identity: String,
    pub scope_digest: String,
    pub observed_at: String,
    pub recorded_at: String,
    pub evidence_digest: String,
    pub freshness_ceiling_seconds: i64,
    pub complete: bool,
    pub truncated: bool,
    pub conflicting: bool,
    pub synthetic: bool,
    pub provider_error: Option<String>,
    pub outcome: FrameworkSatisfactionStatus,
    pub evidence_role: String,
    pub process_phase: String,
    pub inventory_generation: Option<String>,
    pub hierarchy_generation: Option<String>,
    pub not_applicable_justification: Option<String>,
    pub not_applicable_requested_by: Option<String>,
    pub not_applicable_approved_by: Option<String>,
    pub approval_expires_at: Option<String>,
    #[allow(clippy::type_complexity)]
    pub rule_provenance: Option<Box<FrameworkRuleProvenance>>,
    pub limitations: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FrameworkTradeoffRecord {
    pub tradeoff_id: String,
    pub scope_digest: String,
    pub affected_control_ids: Vec<String>,
    pub decision_owner: String,
    pub rationale_digest: String,
    pub approved_at: String,
    pub expires_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FrameworkAssessmentRequest {
    pub assessment_id: String,
    pub profile: Box<FrameworkAssessmentProfile>,
    pub evaluated_at: String,
    pub recorded_at: String,
    pub evidence: Vec<FrameworkEvidenceReceipt>,
    pub tradeoffs: Vec<FrameworkTradeoffRecord>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FrameworkRequirementResult {
    pub requirement_id: String,
    pub status: FrameworkSatisfactionStatus,
    pub evidence_refs: Vec<String>,
    pub evidence_digests: Vec<String>,
    pub limitations: Vec<String>,
}

impl FrameworkRequirementResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.requirement_id.trim().is_empty() { return Err("requirement_id must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FrameworkControlResult {
    pub control_id: String,
    pub title: String,
    pub area: String,
    pub reference_state: String,
    pub mapping_state: String,
    pub applicability: FrameworkApplicabilityStatus,
    pub evaluation: FrameworkEvaluationStatus,
    pub satisfaction: FrameworkSatisfactionStatus,
    pub owner_slot: String,
    pub cadence_days: i64,
    pub evidence_complete: bool,
    pub evidence_refs: Vec<String>,
    pub evidence_digests: Vec<String>,
    pub limitations: Vec<String>,
    pub requirements: Vec<FrameworkRequirementResult>,
    pub enablement: Option<String>,
}

impl FrameworkControlResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.control_id.trim().is_empty() { return Err("control_id must be non-empty"); }
        if self.title.trim().is_empty() { return Err("title must be non-empty"); }
        if self.area.trim().is_empty() { return Err("area must be non-empty"); }
        if self.reference_state.trim().is_empty() { return Err("reference_state must be non-empty"); }
        if self.mapping_state.trim().is_empty() { return Err("mapping_state must be non-empty"); }
        if self.owner_slot.trim().is_empty() { return Err("owner_slot must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FrameworkAssessmentResult {
    pub assessment_id: String,
    pub mode: String,
    pub execution_authority: bool,
    pub framework_id: String,
    pub framework_version: String,
    pub catalog_digest: String,
    pub profile_id: String,
    pub profile_digest: String,
    pub profile_reviewed_by: String,
    pub profile_reviewed_at: String,
    pub applicability_profile: Vec<FrameworkApplicabilityDecision>,
    pub ontology_release: String,
    pub scope_digest: String,
    pub inventory_generation: Option<String>,
    pub hierarchy_generation: Option<String>,
    pub evaluated_at: String,
    pub recorded_at: String,
    pub controls: Vec<FrameworkControlResult>,
    pub tradeoffs: Vec<FrameworkTradeoffRecord>,
    pub aggregate_counts: BTreeMap<String, i64>,
    pub result_digest: String,
}

pub const SHA256: &str = "^sha256:[a-f0-9]{64}$";
pub const LIMITATION_CODE: &str = "^[a-z][a-z0-9_]{0,63}$";
pub const RULE_ACTIVATION_GENERATION_ID: &str = "^rule-activation-[a-f0-9]{32}$";
impl FrameworkApplicabilityDecision {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        let mut value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("control_id"), self.control_id.clone()), (String::from("status"), String::new()), (String::from("requested_by"), self.requested_by.clone()), (String::from("owner_slot"), self.owner_slot.clone()), (String::from("cadence_days"), String::new())]);
        value.clone()
    }
}

impl FrameworkOwnerBinding {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("control_id"), self.control_id.clone()), (String::from("owner_slot"), self.owner_slot.clone()), (String::from("owner_identity"), self.owner_identity.clone())])
    }
}

impl FrameworkRuleActivationPin {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("generation_id"), self.generation_id.clone()), (String::from("generation_digest"), self.generation_digest.clone()), (String::from("rule_catalog_digest"), self.rule_catalog_digest.clone())])
    }
}

impl FrameworkAssessmentProfile {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn create(mut values: std::collections::BTreeMap<String, String>) -> FrameworkAssessmentProfile {
        let mut material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("profile_id"), String::new()), (String::from("framework_id"), String::new()), (String::from("framework_version"), String::new()), (String::from("catalog_digest"), String::new()), (String::from("scope_kind"), String::new()), (String::from("scope_digest"), String::new()), (String::from("ontology_release"), String::new()), (String::from("applicability"), String::new()), (String::from("owners"), String::new()), (String::from("reviewed_by"), String::new()), (String::from("reviewed_at"), String::new()), (String::from("inventory_generation"), String::new()), (String::from("hierarchy_generation"), String::new()), (String::from("operating_model"), String::new()), (String::from("environment_classes"), String::new()), (String::from("regulatory_context"), String::new())]);
        let rule_activation: Option<String> = (values.clone()).get("rule_activation").cloned();
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self, mut include_digest: bool) -> std::collections::BTreeMap<String, String> {
        let mut value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("profile_id"), self.profile_id.clone()), (String::from("framework_id"), self.framework_id.clone()), (String::from("framework_version"), self.framework_version.clone()), (String::from("catalog_digest"), self.catalog_digest.clone()), (String::from("scope_kind"), String::new()), (String::from("scope_digest"), self.scope_digest.clone()), (String::from("ontology_release"), self.ontology_release.clone()), (String::from("applicability"), String::new()), (String::from("owners"), String::new()), (String::from("reviewed_by"), self.reviewed_by.clone()), (String::from("reviewed_at"), String::new()), (String::from("inventory_generation"), (self.inventory_generation.clone()).unwrap_or_default()), (String::from("hierarchy_generation"), (self.hierarchy_generation.clone()).unwrap_or_default()), (String::from("operating_model"), (self.operating_model.clone()).unwrap_or_default()), (String::from("environment_classes"), String::new()), (String::from("regulatory_context"), String::new())]);
        if include_digest {
            value.insert(String::from("profile_digest"), self.profile_digest.clone());
        }
        value.clone()
    }
}

impl FrameworkTradeoffRecord {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("tradeoff_id"), self.tradeoff_id.clone()), (String::from("scope_digest"), self.scope_digest.clone()), (String::from("affected_control_ids"), String::new()), (String::from("decision_owner"), self.decision_owner.clone()), (String::from("rationale_digest"), self.rationale_digest.clone()), (String::from("approved_at"), String::new()), (String::from("expires_at"), String::new())])
    }
}

impl FrameworkRequirementResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("requirement_id"), self.requirement_id.clone()), (String::from("status"), String::new()), (String::from("evidence_refs"), String::new()), (String::from("evidence_digests"), String::new()), (String::from("limitations"), String::new())])
    }
}

impl FrameworkControlResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        let mut value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("control_id"), self.control_id.clone()), (String::from("title"), self.title.clone()), (String::from("area"), self.area.clone()), (String::from("reference_state"), self.reference_state.clone()), (String::from("mapping_state"), self.mapping_state.clone()), (String::from("applicability"), String::new()), (String::from("evaluation"), String::new()), (String::from("satisfaction"), String::new()), (String::from("owner_slot"), self.owner_slot.clone()), (String::from("cadence_days"), String::new()), (String::from("evidence_complete"), String::new()), (String::from("evidence_refs"), String::new()), (String::from("evidence_digests"), String::new()), (String::from("limitations"), String::new()), (String::from("requirements"), String::new())]);
        value.clone()
    }
}

impl FrameworkAssessmentResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self, mut include_digest: bool) -> std::collections::BTreeMap<String, String> {
        let mut value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("assessment_id"), self.assessment_id.clone()), (String::from("mode"), self.mode.clone()), (String::from("execution_authority"), String::new()), (String::from("framework_id"), self.framework_id.clone()), (String::from("framework_version"), self.framework_version.clone()), (String::from("catalog_digest"), self.catalog_digest.clone()), (String::from("profile_id"), self.profile_id.clone()), (String::from("profile_digest"), self.profile_digest.clone()), (String::from("profile_reviewed_by"), self.profile_reviewed_by.clone()), (String::from("profile_reviewed_at"), String::new()), (String::from("applicability_profile"), String::new()), (String::from("ontology_release"), self.ontology_release.clone()), (String::from("scope_digest"), self.scope_digest.clone()), (String::from("inventory_generation"), (self.inventory_generation.clone()).unwrap_or_default()), (String::from("hierarchy_generation"), (self.hierarchy_generation.clone()).unwrap_or_default()), (String::from("evaluated_at"), String::new()), (String::from("recorded_at"), String::new()), (String::from("controls"), String::new()), (String::from("tradeoffs"), String::new()), (String::from("aggregate_counts"), String::new())]);
        if include_digest {
            value.insert(String::from("result_digest"), self.result_digest.clone());
        }
        value.clone()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_text(mut label: String, mut value: String) -> Result<(), &'static str> {
    if ((value.clone()).trim().to_string()).is_empty() {
        return Err("label MUST be non-empty");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_aware(mut label: String, mut value: String) -> Result<(), &'static str> {
    if label.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_digest(mut label: String, mut value: String) -> Result<(), &'static str> {
    if label.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["FrameworkApplicabilityDecision", "FrameworkApplicabilityStatus", "FrameworkAssessmentProfile", "FrameworkAssessmentRequest", "FrameworkAssessmentResult", "FrameworkControlResult", "FrameworkEvaluationStatus", "FrameworkEvidenceReceipt", "FrameworkOwnerBinding", "FrameworkRequirementResult", "FrameworkSatisfactionStatus", "FrameworkTradeoffRecord"];
