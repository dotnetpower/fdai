pub const MAX_ID_LENGTH: i64 = 512;
pub const MAX_REASONS: i64 = 32;
pub const MAX_REFS: i64 = 256;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum KubernetesPodDiagnosisStatus {
    #[default]
    OomKilled,
    ProbeFailureEvidence,
    NormalExit,
    AbnormalExit,
    InsufficientEvidence,
    ConflictingEvidence,
}

impl KubernetesPodDiagnosisStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::OomKilled => "oom_killed",
            Self::ProbeFailureEvidence => "probe_failure_evidence",
            Self::NormalExit => "normal_exit",
            Self::AbnormalExit => "abnormal_exit",
            Self::InsufficientEvidence => "insufficient_evidence",
            Self::ConflictingEvidence => "conflicting_evidence",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ContainerTerminationEvidence {
    pub pod_uid: String,
    pub container_name: String,
    pub reason: Option<String>,
    pub exit_code: i64,
    pub signal: Option<i64>,
    pub finished_at: Option<String>,
    pub lifecycle_reasons: Vec<String>,
    pub evidence_refs: Vec<String>,
}

impl ContainerTerminationEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.pod_uid.trim().is_empty() { return Err("pod_uid must be non-empty"); }
        if self.container_name.trim().is_empty() { return Err("container_name must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct KubernetesPodLogEvidence {
    pub pod_uid: String,
    pub start: String,
    pub end: String,
    pub source_identity: String,
    pub complete: bool,
    pub limitation: Option<String>,
    pub total_records: i64,
    pub error_records: i64,
    pub first_recorded_at: Option<String>,
    pub last_recorded_at: Option<String>,
    pub record_digests: Vec<String>,
    pub evidence_refs: Vec<String>,
    pub source_revision: Option<String>,
    pub provider_cutoff: Option<String>,
    pub coverage_receipt_ref: Option<String>,
}

impl KubernetesPodLogEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.pod_uid.trim().is_empty() { return Err("pod_uid must be non-empty"); }
        if self.start.trim().is_empty() { return Err("start must be non-empty"); }
        if self.end.trim().is_empty() { return Err("end must be non-empty"); }
        if self.source_identity.trim().is_empty() { return Err("source_identity must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct KubernetesPodDiagnosisResult {
    pub pod_uid: String,
    pub container_name: Option<String>,
    pub status: KubernetesPodDiagnosisStatus,
    pub complete: bool,
    pub termination_reason: Option<String>,
    pub exit_code: Option<i64>,
    pub signal: Option<i64>,
    pub finished_at: Option<String>,
    pub log_source_identity: String,
    pub log_record_count: i64,
    pub log_error_record_count: i64,
    pub evidence_gaps: Vec<String>,
    pub evidence_refs: Vec<String>,
    pub cause_claim_supported: bool,
    pub execution_authority: bool,
}

impl KubernetesPodDiagnosisResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.cause_claim_supported { return Err("cause_claim_supported violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn assess_kubernetes_pod_diagnosis(mut pod_uid: String, mut termination: Option<ContainerTerminationEvidence>, mut logs: KubernetesPodLogEvidence, mut cutoff: String) -> Result<KubernetesPodDiagnosisResult, &'static str> {
    if ((pod_uid.trim().to_string()).is_empty()) || ((((pod_uid.clone()).len() as i64)) > (MAX_ID_LENGTH)) {
        return Err("pod_uid MUST be bounded non-empty text");
    }
    let mut gaps: Vec<String> = Vec::<String>::new();
    let mut conflicts: Vec<String> = Vec::<String>::new();
    if (logs.pod_uid.clone()) != (pod_uid.clone()) {
        conflicts.push(String::from("log_pod_uid_conflict"));
    }
    if (logs.end.clone()) != (cutoff.clone()) {
        conflicts.push(String::from("log_cutoff_conflict"));
    }
    if !(logs.complete) {
        gaps.push(format!("logs_{}", (logs.limitation.clone()).unwrap_or_else(|| String::from("incomplete"))));
    }
    if termination.is_none() {
        gaps.push(String::from("termination_unavailable"));
    } else {
        let mut status: KubernetesPodDiagnosisStatus = termination_status(Default::default(), conflicts.clone(), gaps.clone());
    }
    let complete: bool = ((gaps.clone()).is_empty()) && ((conflicts.clone()).is_empty());
    Ok(KubernetesPodDiagnosisResult { pod_uid: pod_uid.clone(), complete: complete, log_source_identity: logs.source_identity.clone(), log_record_count: logs.total_records, log_error_record_count: logs.error_records, ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn termination_status(mut termination: ContainerTerminationEvidence, mut conflicts: Vec<String>, mut gaps: Vec<String>) -> KubernetesPodDiagnosisStatus {
    let reason: Option<String> = termination.reason.clone();
    if (reason.clone()) == Some(String::from("OOMKilled")) {
        if (termination.exit_code) != (137_i64) {
            conflicts.push(String::from("oom_exit_code_conflict"));
        }
    }
    if (termination.lifecycle_reasons.clone()).contains(&(String::from("Unhealthy"))) {
        if (termination.exit_code) == (0_i64) {
            conflicts.push(String::from("probe_failure_exit_code_conflict"));
        }
    }
    if (reason.clone()) == Some(String::from("Completed")) {
        if (termination.exit_code) != (0_i64) {
            conflicts.push(String::from("completed_exit_code_conflict"));
        }
    }
    gaps.push(String::from("termination_classification_unavailable"));
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_bounded_unique(mut values: Vec<String>, mut field: String, mut limit: i64) -> Result<(), &'static str> {
    if ((((values.clone()).len() as i64)) > (limit)) || ((((values.clone()).len() as i64)) != ((((values.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64))) {
        return Err("field MUST be unique within its bound");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ContainerTerminationEvidence", "KubernetesPodDiagnosisResult", "KubernetesPodDiagnosisStatus", "KubernetesPodLogEvidence", "assess_kubernetes_pod_diagnosis"];
