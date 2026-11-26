#[derive(Clone, Debug, Default, PartialEq)]
pub struct SafeguardDispatchEvidenceIdentity {
    pub schema_version: String,
    pub action_id: String,
    pub target_digest: String,
    pub target_fence_identity_digest: String,
    pub target_fence_record_digest: String,
    pub target_fence_generation: i64,
    pub target_fence_revision: i64,
    pub reservation_identity_digest: String,
    pub reservation_attempt: i64,
    pub acquisition_receipt_digest: String,
    pub reservation_receipt_digest: String,
    pub reservation_record_digest: String,
    pub reservation_revision: i64,
    pub reservation_lease_expires_at: String,
    pub audit_append_receipt_digest: String,
    pub lock_assessment_digest: String,
    pub lock_assessment_valid_until: String,
    pub lock_proof_digest: String,
    pub idempotency_proof_digest: String,
    pub audit_intent_proof_digest: String,
    pub pre_bundle_commitment_digest: String,
    pub lock_verifier_id: String,
    pub lock_verifier_version: String,
    pub lock_trust_anchor_id: String,
    pub safeguard_bundle_digest: String,
    pub continuity_policy_digest: String,
    pub execution_path: String,
    pub execution_fingerprint: String,
    pub source_revision: String,
    pub client_correlation_id: String,
    pub sink_idempotency_key: String,
    pub identity_digest: String,
    pub execution_origin: Option<String>,
    pub execution_venue: Option<String>,
    pub execution_authority: bool,
    pub effect_verification_authority: bool,
}

impl SafeguardDispatchEvidenceIdentity {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0" | "1.1.0") { return Err("invalid schema_version literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.effect_verification_authority { return Err("effect_verification_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const PROVENANCE_FIELDS: &[&str] = &["execution_origin", "execution_venue"];
impl SafeguardDispatchEvidenceIdentity {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn validate_provenance(&self) -> Result<(), &'static str> {
        if (self.schema_version.clone()) == (String::from("1.0.0")) {
            if (self.execution_origin.is_some()) || (self.execution_venue.is_some()) {
                return Err("safeguard dispatch evidence identity 1.0.0 predates execution provenance");
            }
            return Ok(());
        }
        if (self.execution_origin.is_none()) || (self.execution_venue.is_none()) {
            return Err("safeguard dispatch evidence identity MUST bind execution origin and venu");
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn binds_execution_provenance(&self) -> bool {
        (self.execution_origin.is_some()) && (self.execution_venue.is_some())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn create(mut preparing_fence: String, mut persistence_context: String, mut bundle: String) -> Result<String, &'static str> {
        let mut values: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.1.0")), (String::from("action_id"), String::new()), (String::from("target_digest"), String::new()), (String::from("target_fence_identity_digest"), String::new()), (String::from("target_fence_record_digest"), String::new()), (String::from("target_fence_generation"), String::new()), (String::from("target_fence_revision"), String::new()), (String::from("reservation_identity_digest"), String::new()), (String::from("reservation_attempt"), String::new()), (String::from("acquisition_receipt_digest"), String::new()), (String::from("reservation_receipt_digest"), String::new()), (String::from("reservation_record_digest"), String::new()), (String::from("reservation_revision"), String::new()), (String::from("reservation_lease_expires_at"), String::new()), (String::from("audit_append_receipt_digest"), String::new()), (String::from("lock_assessment_digest"), String::new()), (String::from("lock_assessment_valid_until"), String::new()), (String::from("lock_proof_digest"), String::new()), (String::from("idempotency_proof_digest"), String::new()), (String::from("audit_intent_proof_digest"), String::new()), (String::from("pre_bundle_commitment_digest"), String::new()), (String::from("lock_verifier_id"), String::new()), (String::from("lock_verifier_version"), String::new()), (String::from("lock_trust_anchor_id"), String::new()), (String::from("safeguard_bundle_digest"), String::new()), (String::from("continuity_policy_digest"), String::new()), (String::from("execution_path"), String::new()), (String::from("execution_fingerprint"), String::new()), (String::from("source_revision"), String::new()), (String::from("client_correlation_id"), String::new()), (String::from("sink_idempotency_key"), String::new()), (String::from("execution_origin"), String::new()), (String::from("execution_venue"), String::new()), (String::from("execution_authority"), String::new()), (String::from("effect_verification_authority"), String::new())]);
        Ok(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn digest_body(mut values: std::collections::BTreeMap<String, String>, mut schema_version: String) -> std::collections::BTreeMap<String, String> {
    if (schema_version.clone()) != (String::from("1.0.0")) {
        return values.clone();
    }
    std::collections::BTreeMap::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PROVENANCE_FIELDS", "IdentitySchemaVersion", "SafeguardDispatchEvidenceIdentity"];
