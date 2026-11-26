use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct RemediationProposalBinding {
    pub publisher: String,
    pub levers: BTreeMap<String, String>,
}

pub trait PostureAssessmentProvider {
    fn findings_for_scope(&self, scope: String) -> Vec<String>;
}

pub trait ReadinessReportPublisher {
    fn publish_readiness_report(&self, report: std::collections::BTreeMap<String, String>);
}

pub trait RemediationProposalPublisher {
    fn publish_remediation_proposal(&self, proposal: std::collections::BTreeMap<String, String>);
}

pub trait ChecklistEvidenceProvider {
    fn outcomes_for_scope(&self, scope: String) -> Vec<String>;
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChecklistEvidenceProvider", "PostureAssessmentProvider", "ReadinessReportPublisher", "RemediationProposalBinding", "RemediationProposalPublisher"];
