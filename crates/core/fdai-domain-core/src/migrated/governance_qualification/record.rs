use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Readiness {
    #[default]
    ReadyForReview,
    Blocked,
}

impl Readiness {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ReadyForReview => "ready_for_review",
            Self::Blocked => "blocked",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct QualificationBinding {
    pub installation_id: String,
    pub management_scope_id: String,
    pub environment_class: String,
    pub rule_generation_digest: String,
    pub ontology_release_digest: String,
    pub provider_revisions: BTreeMap<String, String>,
    pub evidence_cutoff: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct QualificationRecord {
    pub binding: Box<QualificationBinding>,
    pub readiness: Readiness,
    pub blocking_reasons: Vec<String>,
    pub sources_digest: String,
    pub measurement_digest: Option<String>,
    pub record_digest: String,
    pub authority: String,
}

pub const QUALIFICATION_SCHEMA: &str = "fdai.governance-qualification-record.v1";
pub const DIGEST: &str = "^sha256:[a-f0-9]{64}$";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_qualification_record(mut binding: QualificationBinding, mut sources: String, mut measurement: Option<String>) -> QualificationRecord {
    let mut reasons: Vec<String> = Vec::<String>::new();
    if measurement.is_none() {
        reasons.push(String::from("cohort_not_measured"));
    }
    let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from(QUALIFICATION_SCHEMA)), (String::from("installation_id"), binding.installation_id.clone()), (String::from("management_scope_id"), binding.management_scope_id.clone()), (String::from("environment_class"), binding.environment_class.clone()), (String::from("rule_generation_digest"), binding.rule_generation_digest.clone()), (String::from("ontology_release_digest"), binding.ontology_release_digest.clone()), (String::from("provider_revisions"), String::new()), (String::from("evidence_cutoff"), String::new()), (String::from("readiness"), String::new()), (String::from("blocking_reasons"), String::new()), (String::from("sources_digest"), String::new()), (String::from("measurement_digest"), String::new()), (String::from("authority"), String::from("none"))]);
    QualificationRecord { binding: Box::new(binding.clone()), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn reconcile_ledger_digests(mut record: QualificationRecord, mut ledger_digests: Vec<String>) -> Vec<String> {
    let mut required: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([record.record_digest.clone(), record.sources_digest.clone()]);
    if (record.measurement_digest.clone()).is_some() {
        required.insert((record.measurement_digest.clone()).unwrap_or_default());
    }
    Vec::new()
}

