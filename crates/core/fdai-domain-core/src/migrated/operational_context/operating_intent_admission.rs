pub const MAX_OPERATING_INTENT_ADMISSION_AGE_SECONDS: i64 = 86400;
pub const MAX_ADMITTED_OBJECT_IDS: i64 = 4096;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OperatingIntentAdmissionStatus {
    #[default]
    Unbound,
    Admitted,
    Expired,
    Quarantined,
    Unavailable,
    Malformed,
    BindingMismatch,
}

impl OperatingIntentAdmissionStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Unbound => "unbound",
            Self::Admitted => "admitted",
            Self::Expired => "expired",
            Self::Quarantined => "quarantined",
            Self::Unavailable => "unavailable",
            Self::Malformed => "malformed",
            Self::BindingMismatch => "binding_mismatch",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatingIntentAdmissionExpectation {
    pub expected_revision: String,
    pub expected_sha256: String,
    pub generation: i64,
}

impl OperatingIntentAdmissionExpectation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.expected_revision.trim().is_empty() { return Err("expected_revision must be non-empty"); }
        if self.expected_sha256.trim().is_empty() { return Err("expected_sha256 must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatingIntentAdmission {
    pub status: OperatingIntentAdmissionStatus,
    pub grants_intent_authority: bool,
    pub reason: Option<String>,
    pub source_revision: Option<String>,
    pub snapshot_digest: Option<String>,
    pub generation: Option<i64>,
    #[allow(clippy::type_complexity)]
    pub owned_object_ids: Option<Vec<String>>,
    pub validated_at: Option<String>,
}

pub const SHA256: &str = "^sha256:[0-9a-f]{64}$";
pub const OPERATING_INTENT_SOURCE_ADMISSION_KEY: &str = "operating-intent-source:admission";
pub const DENYING_RECORD_STATUSES: &[&str] = &["quarantined", "unavailable"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StateStoreOperatingIntentAdmissionReader {
    pub initialized: bool,
}

impl StateStoreOperatingIntentAdmissionReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn resolve(&self, mut now: String) -> OperatingIntentAdmission {
        evaluate_operating_intent_admission(None, now.clone(), None).unwrap_or_else(|_| Default::default())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn evaluate_operating_intent_admission(mut raw: Option<std::collections::BTreeMap<String, String>>, mut now: String, mut expectation: Option<OperatingIntentAdmissionExpectation>) -> Result<OperatingIntentAdmission, &'static str> {
    let Some(mut expectation) = expectation.clone() else { return Ok(OperatingIntentAdmission { grants_intent_authority: true, reason: Some(String::from("no deployment-owned operating-intent source binding is configured")), ..Default::default() }); };
    let Some(mut raw) = raw.clone() else { return Ok(OperatingIntentAdmission { grants_intent_authority: false, reason: Some(String::from("a deployment-owned operating-intent source is configured but no current \" \"admission record exists")), ..Default::default() }); };
    let status: Option<String> = (raw.clone()).get("status").cloned();
    let reason: Option<String> = (raw.clone()).get("reason").cloned();
    let reason_text: Option<String> = if (true) && ((reason.clone()).is_some()) { reason.clone() } else { None };
    if (status.clone()) == Some(String::from("unconfigured")) {
        return Ok(binding_mismatch(String::from("the durable admission reports an unconfigured binding while this consumer is \" \"configured")));
    }
    if (status.clone()) != Some(String::from("admitted")) {
        return Ok(malformed(String::from("operating intent admission status is missing or unrecognized")));
    }
    let source_revision: Option<String> = (raw.clone()).get("source_revision").cloned();
    let snapshot_digest: Option<String> = (raw.clone()).get("snapshot_digest").cloned();
    if (!(true)) || ((((source_revision.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
        return Ok(malformed(String::from("admitted operating intent admission is missing source_revision")));
    }
    let generation: Option<String> = (raw.clone()).get("binding_generation").cloned();
    if (source_revision.clone()) != Some(expectation.expected_revision.clone()) {
        return Ok(binding_mismatch(String::from("the durable admission pins a different source revision than this consumer's binding")));
    }
    if (snapshot_digest.clone()) != Some(expectation.expected_sha256.clone()) {
        return Ok(binding_mismatch(String::from("the durable admission pins a different whole-document digest than this consumer's \" \"binding")));
    }
    let owned_object_ids: Option<std::collections::BTreeSet<String>> = owned_object_ids(String::new());
    let Some(mut owned_object_ids) = owned_object_ids.clone() else { return Ok(malformed(String::from("admitted operating intent admission has an unusable owned_object_ids"))); };
    let validated_at: Option<String> = optional_timestamp(String::new());
    let Some(mut validated_at) = validated_at.clone() else { return Ok(malformed(String::from("admitted operating intent admission is missing validated_at"))); };
    let max_age_seconds: Option<String> = (raw.clone()).get("max_age_seconds").cloned();
    Ok(OperatingIntentAdmission { grants_intent_authority: true, source_revision: source_revision.clone(), snapshot_digest: snapshot_digest.clone(), validated_at: Some(validated_at.clone()), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn malformed(mut reason: String) -> OperatingIntentAdmission {
    OperatingIntentAdmission { grants_intent_authority: false, reason: Some(reason.clone()), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn binding_mismatch(mut reason: String) -> OperatingIntentAdmission {
    OperatingIntentAdmission { grants_intent_authority: false, reason: Some(reason.clone()), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn owned_object_ids(mut value: String) -> Option<std::collections::BTreeSet<String>> {
    if (!(false)) || ((((value.clone()).len() as i64)) > (MAX_ADMITTED_OBJECT_IDS)) {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn optional_timestamp(mut value: String) -> Option<String> {
    if !(true) {
        return None;
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["MAX_ADMITTED_OBJECT_IDS", "MAX_OPERATING_INTENT_ADMISSION_AGE_SECONDS", "OPERATING_INTENT_SOURCE_ADMISSION_KEY", "OperatingIntentAdmission", "OperatingIntentAdmissionExpectation", "OperatingIntentAdmissionStatus", "StateStoreOperatingIntentAdmissionReader", "evaluate_operating_intent_admission"];
