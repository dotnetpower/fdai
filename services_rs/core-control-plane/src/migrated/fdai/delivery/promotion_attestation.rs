#[derive(Clone, Debug, Default, PartialEq)]
pub struct GovernancePromotionAttestation {
    pub review: String,
    pub action_type_id: String,
    pub fdai_revision: String,
    pub scenario_set_version: String,
    pub evidence_digest: String,
    pub idempotency_key: String,
    pub nonce: String,
    pub request_fingerprint: String,
}

impl GovernancePromotionAttestation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn as_json(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("action_type_id"), self.action_type_id.clone()), (String::from("fdai_revision"), self.fdai_revision.clone()), (String::from("scenario_set_version"), self.scenario_set_version.clone()), (String::from("evidence_digest"), self.evidence_digest.clone()), (String::from("idempotency_key"), self.idempotency_key.clone()), (String::from("nonce"), self.nonce.clone()), (String::from("request_fingerprint"), self.request_fingerprint.clone()), (String::from("review"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn attestation_from_json(mut raw: std::collections::BTreeMap<String, String>) -> Result<GovernancePromotionAttestation, &'static str> {
    let review_raw: std::collections::BTreeMap<String, String> = mapping(String::new(), String::from("review")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let author_raw: std::collections::BTreeMap<String, String> = mapping(String::new(), String::from("author")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let mut approvals: Vec<String> = Vec::<String>::new();
    let raw_approvals: Option<String> = (review_raw.clone()).get("approvals").cloned();
    if !(true) {
        return Err("promotion attestation approvals are malformed");
    }
    Ok(GovernancePromotionAttestation { action_type_id: text(raw.clone(), String::from("action_type_id")).unwrap_or_else(|_| String::new()), fdai_revision: text(raw.clone(), String::from("fdai_revision")).unwrap_or_else(|_| String::new()), scenario_set_version: text(raw.clone(), String::from("scenario_set_version")).unwrap_or_else(|_| String::new()), evidence_digest: text(raw.clone(), String::from("evidence_digest")).unwrap_or_else(|_| String::new()), idempotency_key: text(raw.clone(), String::from("idempotency_key")).unwrap_or_else(|_| String::new()), nonce: text(raw.clone(), String::from("nonce")).unwrap_or_else(|_| String::new()), request_fingerprint: text(raw.clone(), String::from("request_fingerprint")).unwrap_or_else(|_| String::new()), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn direct_api_receipt_json(mut receipt: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("outcome"), String::new()), (String::from("receipt_ref"), String::new()), (String::from("already_existed"), String::new()), (String::from("rollback_succeeded"), String::new()), (String::from("detail"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn direct_api_receipt_from_json(mut raw: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    let receipt_ref: Option<String> = (raw.clone()).get("receipt_ref").cloned();
    if (!(true)) || (!((receipt_ref.clone()).is_some())) {
        return Err("promotion replay receipt is malformed");
    }
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn promotion_attestation_digest(mut attestation: GovernancePromotionAttestation) -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn mapping(mut value: String, mut name: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !(false) {
        return Err("promotion attestation name is malformed");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut raw: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    let value: Option<String> = (raw.clone()).get(name.as_str()).cloned();
    if (!(true)) || ((((value.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
        return Err("promotion attestation name is malformed");
    }
    Ok((value.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bool(mut raw: std::collections::BTreeMap<String, String>, mut name: String) -> Result<bool, &'static str> {
    let value: Option<String> = (raw.clone()).get(name.as_str()).cloned();
    if !(true) {
        return Err("promotion attestation name is malformed");
    }
    Ok(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn timestamp(mut raw: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    let value: String = text(raw.clone(), name.clone()).unwrap_or_else(|_| String::new());
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn approval_profile(mut value: String) -> Option<String> {
    if false {
        return None;
    }
    let raw: std::collections::BTreeMap<String, String> = mapping(value.clone(), String::from("approval_profile")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let operator: Option<String> = (raw.clone()).get("operator_principal").cloned();
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn optional_timestamp(mut value: String) -> Option<String> {
    if (!(true)) || ((value.clone()).is_empty()) {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn roles(mut value: String) -> std::collections::BTreeSet<String> {
    std::collections::BTreeSet::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn strings(mut value: String) -> Result<Vec<String>, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["GovernancePromotionAttestation", "attestation_from_json", "direct_api_receipt_from_json", "direct_api_receipt_json", "optional_timestamp"];
