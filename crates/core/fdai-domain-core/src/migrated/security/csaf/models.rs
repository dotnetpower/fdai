use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CsafExposureStatus {
    #[default]
    Affected,
    Mitigated,
    Fixed,
    NotApplicable,
    Unknown,
}

impl CsafExposureStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Affected => "affected",
            Self::Mitigated => "mitigated",
            Self::Fixed => "fixed",
            Self::NotApplicable => "not_applicable",
            Self::Unknown => "unknown",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CsafEvaluationStatus {
    #[default]
    Evaluated,
    NotEvaluated,
    Blocked,
}

impl CsafEvaluationStatus {
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
pub enum CsafVexJustification {
    #[default]
    ComponentNotPresent,
    VulnerableCodeNotInExecutePath,
    InlineMitigationsAlreadyExist,
    PatchedVersionDeployed,
    AffectedRequiresRemediation,
    UndeterminedEvidenceGap,
}

impl CsafVexJustification {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ComponentNotPresent => "component_not_present",
            Self::VulnerableCodeNotInExecutePath => "vulnerable_code_not_in_execute_path",
            Self::InlineMitigationsAlreadyExist => "inline_mitigations_already_exist",
            Self::PatchedVersionDeployed => "patched_version_deployed",
            Self::AffectedRequiresRemediation => "affected_requires_remediation",
            Self::UndeterminedEvidenceGap => "undetermined_evidence_gap",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CsafScopedResource {
    pub resource_id: String,
    pub provider_resource_type: String,
    pub observed_at: String,
    pub properties: BTreeMap<String, String>,
    pub workload_tags: Vec<String>,
}

impl CsafScopedResource {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.resource_id.trim().is_empty() { return Err("resource_id must be non-empty"); }
        if self.provider_resource_type.trim().is_empty() { return Err("provider_resource_type must be non-empty"); }
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CsafEvidenceReceipt {
    pub cve_id: String,
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
    pub outcome: CsafExposureStatus,
}

impl CsafEvidenceReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.cve_id.trim().is_empty() { return Err("cve_id must be non-empty"); }
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
pub struct CsafAssessmentRequest {
    pub assessment_id: String,
    pub source_revision: String,
    pub crosswalk_digest: String,
    pub advisories_digest: String,
    pub ontology_release: String,
    pub inventory_generation: String,
    pub workload_id: String,
    pub resources: Vec<CsafScopedResource>,
    pub evaluated_at: String,
    pub recorded_at: String,
    pub evidence: Vec<CsafEvidenceReceipt>,
}

impl CsafAssessmentRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.assessment_id.trim().is_empty() { return Err("assessment_id must be non-empty"); }
        if self.source_revision.trim().is_empty() { return Err("source_revision must be non-empty"); }
        if self.crosswalk_digest.trim().is_empty() { return Err("crosswalk_digest must be non-empty"); }
        if self.advisories_digest.trim().is_empty() { return Err("advisories_digest must be non-empty"); }
        if self.ontology_release.trim().is_empty() { return Err("ontology_release must be non-empty"); }
        if self.inventory_generation.trim().is_empty() { return Err("inventory_generation must be non-empty"); }
        if self.workload_id.trim().is_empty() { return Err("workload_id must be non-empty"); }
        if self.evaluated_at.trim().is_empty() { return Err("evaluated_at must be non-empty"); }
        if self.recorded_at.trim().is_empty() { return Err("recorded_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CsafVulnerabilityFinding {
    pub cve_id: String,
    pub advisory_tracking_id: String,
    pub title: String,
    pub severity: String,
    pub cvss_base_score: f64,
    pub exploit_status: String,
    pub disposition: String,
    pub mapping_state: String,
    pub evaluation: CsafEvaluationStatus,
    pub exposure: CsafExposureStatus,
    pub affected_resource_ids: Vec<String>,
    pub mitigated_resource_ids: Vec<String>,
    pub fixed_resource_ids: Vec<String>,
    pub unknown_resource_ids: Vec<String>,
    pub recommended_action_type: Option<String>,
    pub evidence_refs: Vec<String>,
    pub evidence_digests: Vec<String>,
    pub evidence_complete: bool,
    pub limitations: Vec<String>,
    pub vex_justification: CsafVexJustification,
    pub kev_sla_tier: String,
    pub risk_score: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CsafAssessmentResult {
    pub assessment_id: String,
    pub mode: String,
    pub execution_authority: bool,
    pub source_revision: String,
    pub crosswalk_digest: String,
    pub advisories_digest: String,
    pub ontology_release: String,
    pub inventory_generation: String,
    pub workload_id: String,
    pub scope_digest: String,
    pub evaluated_at: String,
    pub recorded_at: String,
    pub findings: Vec<CsafVulnerabilityFinding>,
    pub aggregate_counts: BTreeMap<String, i64>,
    pub result_digest: String,
}

impl CsafAssessmentResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.assessment_id.trim().is_empty() { return Err("assessment_id must be non-empty"); }
        if self.mode.trim().is_empty() { return Err("mode must be non-empty"); }
        if self.source_revision.trim().is_empty() { return Err("source_revision must be non-empty"); }
        if self.crosswalk_digest.trim().is_empty() { return Err("crosswalk_digest must be non-empty"); }
        if self.advisories_digest.trim().is_empty() { return Err("advisories_digest must be non-empty"); }
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

pub const SHA256_RE: &str = "^sha256:[a-f0-9]{64}$";
pub const CVE_RE: &str = "^(?:CVE-[0-9]{4}-[0-9]{4,7}|ADV[0-9]{6})$";
pub const PROP_KEY_RE: &str = "^[a-z0-9][a-z0-9._:-]{0,127}$";
impl CsafEvidenceReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_admissible(&self) -> bool {
        (!(self.synthetic)) && ((self.provider_error.is_none()) && ((self.complete) && ((!(self.truncated)) && (!(self.conflicting)))))
    }
}

impl CsafAssessmentRequest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn scope_digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

impl CsafVulnerabilityFinding {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("cve_id"), self.cve_id.clone()), (String::from("advisory_tracking_id"), self.advisory_tracking_id.clone()), (String::from("title"), self.title.clone()), (String::from("severity"), String::new()), (String::from("cvss_base_score"), String::new()), (String::from("exploit_status"), String::new()), (String::from("disposition"), String::new()), (String::from("mapping_state"), self.mapping_state.clone()), (String::from("evaluation"), String::new()), (String::from("exposure"), String::new()), (String::from("vex_justification"), String::new()), (String::from("kev_sla_tier"), String::new()), (String::from("risk_score"), String::new()), (String::from("affected_resource_ids"), String::new()), (String::from("mitigated_resource_ids"), String::new()), (String::from("fixed_resource_ids"), String::new()), (String::from("unknown_resource_ids"), String::new()), (String::from("recommended_action_type"), (self.recommended_action_type.clone()).unwrap_or_default()), (String::from("evidence_refs"), String::new()), (String::from("evidence_digests"), String::new()), (String::from("evidence_complete"), String::new()), (String::from("limitations"), String::new())])
    }
}

impl CsafAssessmentResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self, mut include_digest: bool) -> std::collections::BTreeMap<String, String> {
        let mut payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("assessment_id"), self.assessment_id.clone()), (String::from("mode"), self.mode.clone()), (String::from("execution_authority"), String::new()), (String::from("source_revision"), self.source_revision.clone()), (String::from("crosswalk_digest"), self.crosswalk_digest.clone()), (String::from("advisories_digest"), self.advisories_digest.clone()), (String::from("ontology_release"), self.ontology_release.clone()), (String::from("inventory_generation"), self.inventory_generation.clone()), (String::from("workload_id"), self.workload_id.clone()), (String::from("scope_digest"), self.scope_digest.clone()), (String::from("evaluated_at"), String::new()), (String::from("recorded_at"), String::new()), (String::from("findings"), String::new()), (String::from("aggregate_counts"), String::new())]);
        if include_digest {
            payload.insert(String::from("result_digest"), self.result_digest.clone());
        }
        payload.clone()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn compute_csaf_risk_score(mut cvss_base_score: f64, mut exploit_status: String, mut cvss_vector: Option<String>, mut exposure: CsafExposureStatus) -> Result<f64, &'static str> {
    let mut vector_points: f64 = 0.0;
    Ok(0.0_f64)
}

pub const PUBLIC_EXPORTS: &[&str] = &["CsafAssessmentRequest", "CsafAssessmentResult", "CsafEvaluationStatus", "CsafEvidenceReceipt", "CsafExposureStatus", "CsafScopedResource", "CsafVexJustification", "CsafVulnerabilityFinding", "ScalarProperty", "compute_csaf_risk_score"];
