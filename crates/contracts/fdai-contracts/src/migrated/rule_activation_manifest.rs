pub const MAX_REVOCATION_AGE_SECONDS: i64 = 86400;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RuleActivationManifestSource {
    #[default]
    Installation,
    PullRequest,
    OfflinePackage,
}

impl RuleActivationManifestSource {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Installation => "installation",
            Self::PullRequest => "pull_request",
            Self::OfflinePackage => "offline_package",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleRevisionIdentityRef {
    pub rule_id: String,
    pub rule_version: String,
    pub revision_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationManifest {
    pub schema_version: String,
    pub source: RuleActivationManifestSource,
    pub release_id: String,
    pub source_id: String,
    pub target_generation_id: String,
    pub target_generation_digest: String,
    pub profile_id: String,
    pub profile_version: String,
    pub catalog_manifest_digest: String,
    pub revision_registry_root: String,
    pub members: Vec<RuleRevisionIdentityRef>,
    pub deployment_scope_digest: String,
    pub nonce: String,
    pub issued_at: String,
    pub expires_at: String,
    pub approval_authority: bool,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleActivationManifest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if self.approval_authority { return Err("approval_authority violated literal bool invariant"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationTrustedKey {
    pub key_id: String,
    pub public_key: String,
    pub valid_from: String,
    pub valid_until: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationManifestTrust {
    pub schema_version: String,
    pub purpose: String,
    pub approved_by: String,
    pub valid_from: String,
    pub valid_until: String,
    pub keys: Vec<RuleActivationTrustedKey>,
    pub revoked_key_ids: Vec<String>,
    pub revocation_checked_at: String,
    pub revocation_max_age_seconds: i64,
}

impl RuleActivationManifestTrust {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.purpose.as_str(), "fdai.rule-activation-manifest.v1") { return Err("invalid purpose literal"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.revocation_max_age_seconds) { return Err("revocation_max_age_seconds out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SignedRuleActivationManifest {
    pub schema_version: String,
    pub algorithm: String,
    pub key_id: String,
    pub manifest: Box<RuleActivationManifest>,
    pub manifest_digest: String,
    pub signature: String,
}

impl SignedRuleActivationManifest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.algorithm.as_str(), "Ed25519") { return Err("invalid algorithm literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationManifestExpectation {
    pub source: RuleActivationManifestSource,
    pub release_id: String,
    pub source_id: String,
    pub target_generation_id: String,
    pub target_generation_digest: String,
    pub profile_id: String,
    pub profile_version: String,
    pub catalog_manifest_digest: String,
    pub revision_registry_root: String,
    pub members: Vec<RuleRevisionIdentityRef>,
    pub deployment_scope_digest: String,
}

impl RuleRevisionIdentityRef {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn exact_identity(mut value: String) -> String {
        exact_text(value.clone(), String::from("Rule revision identity reference")).unwrap_or_else(|_| String::new())
    }
}

impl RuleActivationManifest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn exact_text_fields(mut value: String) -> String {
        exact_text(value.clone(), String::from("Rule activation manifest")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn aware_utc(mut value: String) -> Result<String, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bounded_manifest(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn manifest_digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

impl RuleActivationTrustedKey {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn exact_key_id(mut value: String) -> String {
        exact_text(value.clone(), String::from("Rule activation key id")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn raw_public_key(mut value: String) -> String {
        let _ = public_key(value.clone());
        value.clone()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn aware_utc(mut value: String) -> String {
        aware(value.clone()).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validity(&self) -> Result<String, &'static str> {
        if (self.valid_until.clone()) <= (self.valid_from.clone()) {
            return Err("Rule activation signing key validity MUST be positive");
        }
        Ok(String::new())
    }
}

impl RuleActivationManifestTrust {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn exact_approved_by(mut value: String) -> String {
        exact_text(value.clone(), String::from("Rule activation trust approver")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn aware_utc(mut value: String) -> String {
        aware(value.clone()).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn unambiguous_trust(&self) -> Result<String, &'static str> {
        if (self.valid_until.clone()) <= (self.valid_from.clone()) {
            return Err("Rule activation trust validity MUST be positive");
        }
        if ((((self.revoked_key_ids.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.revoked_key_ids.clone()).len() as i64)) {
            return Err("Rule activation revoked key ids MUST be unique");
        }
        Ok(String::new())
    }
}

impl SignedRuleActivationManifest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn exact_key_id(mut value: String) -> String {
        exact_text(value.clone(), String::from("signed Rule activation key id")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn digest_and_signature_shape(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
}

impl RuleActivationManifestExpectation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn exact_text_fields(mut value: String) -> String {
        exact_text(value.clone(), String::from("Rule activation manifest expectation")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_members(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn sign_rule_activation_manifest(mut manifest: RuleActivationManifest, mut key_id: String, mut private_key: String) -> SignedRuleActivationManifest {
    SignedRuleActivationManifest { key_id: key_id.clone(), manifest: Box::new(manifest.clone()), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn verify_rule_activation_manifest(mut envelope: SignedRuleActivationManifest, mut trust: RuleActivationManifestTrust, mut now: String, mut expected: RuleActivationManifestExpectation, mut consumed_nonces: Vec<String>) -> Result<RuleActivationManifest, &'static str> {
    let current: String = aware(now.clone()).unwrap_or_else(|_| String::new());
    if !(((trust.valid_from.clone()) <= (current.clone())) && ((current.clone()) < (trust.valid_until.clone()))) {
        return Err("Rule activation manifest trust is not currently valid");
    }
    if (trust.revocation_checked_at.clone()) > (current.clone()) {
        return Err("Rule activation revocation check MUST NOT be future-dated");
    }
    let manifest: RuleActivationManifest = *(envelope.manifest.clone());
    if !(((manifest.issued_at.clone()) <= (current.clone())) && ((current.clone()) < (manifest.expires_at.clone()))) {
        return Err("Rule activation manifest is not currently valid");
    }
    let actual_identity: RuleActivationManifestExpectation = RuleActivationManifestExpectation { source: manifest.source.clone(), release_id: manifest.release_id.clone(), source_id: manifest.source_id.clone(), target_generation_id: manifest.target_generation_id.clone(), target_generation_digest: manifest.target_generation_digest.clone(), profile_id: manifest.profile_id.clone(), profile_version: manifest.profile_version.clone(), catalog_manifest_digest: manifest.catalog_manifest_digest.clone(), revision_registry_root: manifest.revision_registry_root.clone(), members: manifest.members.clone(), deployment_scope_digest: manifest.deployment_scope_digest.clone(), ..Default::default() };
    if (consumed_nonces.clone()).contains(&(manifest.nonce.clone())) {
        return Err("Rule activation manifest nonce was already consumed");
    }
    Ok(manifest.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn rule_revision_registry_root(mut members: Vec<RuleRevisionIdentityRef>) -> Result<String, &'static str> {
    if members.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn manifest_expectation_from_identity_v2(mut source: RuleActivationManifestSource, mut release_id: String, mut source_id: String, mut identity: String, mut deployment_scope_digest: String) -> RuleActivationManifestExpectation {
    RuleActivationManifestExpectation { source: source.clone(), release_id: release_id.clone(), source_id: source_id.clone(), revision_registry_root: rule_revision_registry_root(Vec::new()).unwrap_or_else(|_| String::new()), deployment_scope_digest: deployment_scope_digest.clone(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn signing_bytes(mut manifest: RuleActivationManifest) -> Vec<u8> {
    core::hint::black_box(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn public_key(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn public_key_bytes(mut value: String) -> Result<Vec<u8>, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn signature_bytes(mut value: String) -> Result<Vec<u8>, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn aware(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn exact_text(mut value: String, mut label: String) -> Result<String, &'static str> {
    if (true) && ((value.clone()) != (value.trim().to_string())) {
        return Err("label MUST be exact");
    }
    Ok(value.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuleActivationManifest", "RuleActivationManifestSource", "RuleActivationManifestExpectation", "RuleActivationManifestTrust", "RuleActivationTrustedKey", "RuleRevisionIdentityRef", "SignedRuleActivationManifest", "rule_revision_registry_root", "manifest_expectation_from_identity_v2", "sign_rule_activation_manifest", "verify_rule_activation_manifest"];
