use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CandidateKind {
    #[default]
    Rule,
    Workflow,
    ActionType,
    Policy,
    OntologyObject,
    OntologyLink,
}

impl CandidateKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Rule => "rule",
            Self::Workflow => "workflow",
            Self::ActionType => "action_type",
            Self::Policy => "policy",
            Self::OntologyObject => "ontology_object",
            Self::OntologyLink => "ontology_link",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DistillerAvailability {
    #[default]
    Available,
    Unavailable,
    Abstaining,
}

impl DistillerAvailability {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Available => "available",
            Self::Unavailable => "unavailable",
            Self::Abstaining => "abstaining",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DistillerCapabilityDescriptor {
    pub binding_id: String,
    pub binding_version: String,
    pub contract_version: String,
    pub availability: DistillerAvailability,
    pub reason_code: Option<String>,
}

impl DistillerCapabilityDescriptor {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.binding_id.trim().is_empty() { return Err("binding_id must be non-empty"); }
        if self.binding_version.trim().is_empty() { return Err("binding_version must be non-empty"); }
        if self.contract_version.trim().is_empty() { return Err("contract_version must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ManualLineProvenance {
    pub line_number: i64,
    pub source_format: String,
    pub unit_id: String,
    pub locator: String,
}

impl ManualLineProvenance {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.source_format.trim().is_empty() { return Err("source_format must be non-empty"); }
        if self.unit_id.trim().is_empty() { return Err("unit_id must be non-empty"); }
        if self.locator.trim().is_empty() { return Err("locator must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ManualDocument {
    pub doc_id: String,
    pub text: String,
    pub source_ref: String,
    pub content_sha: String,
    pub metadata: BTreeMap<String, String>,
    pub line_provenance: Vec<ManualLineProvenance>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DistilledCandidate {
    pub kind: CandidateKind,
    pub candidate_id: String,
    pub source_ref: String,
    pub source_section: String,
    pub source_lines: String,
    pub content_sha: String,
    pub body: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CoverageGap {
    pub line: i64,
    pub text: String,
    pub kind: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CoverageReport {
    pub total: i64,
    pub covered: i64,
    pub gaps: Vec<CoverageGap>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DistillationResult {
    pub candidates: Vec<DistilledCandidate>,
    pub coverage: Box<CoverageReport>,
    pub council_receipts: Vec<String>,
}

impl CoverageReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn coverage_ratio(&self) -> f64 {
        if (self.total) <= (0_i64) {
            return 1.0;
        }
        0.0_f64
    }
}

pub trait Distiller {
    fn distill(&self, document: ManualDocument) -> DistillationResult;
}

pub trait DescribedDistiller {
    fn distiller_capability(&self) -> DistillerCapabilityDescriptor;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AbstainingDistiller {
    pub initialized: bool,
}

impl AbstainingDistiller {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn distill(&self, mut document: ManualDocument) -> DistillationResult {
        DistillationResult::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn distiller_capability(&self) -> DistillerCapabilityDescriptor {
        DistillerCapabilityDescriptor { binding_id: String::from("upstream-abstaining-distiller"), binding_version: String::from("1.0.0"), contract_version: String::from("ontology-distiller-conformance.v1"), reason_code: Some(String::from("provider_unbound")), ..Default::default() }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn describe_distiller(mut distiller: String) -> DistillerCapabilityDescriptor {
    DistillerCapabilityDescriptor { binding_version: String::from("unknown"), contract_version: String::from("ontology-distiller-conformance.v1"), reason_code: Some(String::from("descriptor_unavailable")), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AbstainingDistiller", "CandidateKind", "CoverageGap", "CoverageReport", "DescribedDistiller", "DistillationResult", "DistilledCandidate", "Distiller", "DistillerAvailability", "DistillerCapabilityDescriptor", "ManualDocument", "ManualLineProvenance", "describe_distiller"];
