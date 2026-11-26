#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CouncilOutcome {
    #[default]
    Consensus,
    Contested,
    Unsupported,
    Unresolved,
}

impl CouncilOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Consensus => "consensus",
            Self::Contested => "contested",
            Self::Unsupported => "unsupported",
            Self::Unresolved => "unresolved",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilModelReceipt {
    pub publisher: String,
    pub family: String,
    pub version: String,
    pub deployment: String,
    pub binding: String,
    pub fault_domain: String,
    pub identity_digest: String,
}

impl CouncilModelReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.publisher.trim().is_empty() { return Err("publisher must be non-empty"); }
        if self.family.trim().is_empty() { return Err("family must be non-empty"); }
        if self.version.trim().is_empty() { return Err("version must be non-empty"); }
        if self.deployment.trim().is_empty() { return Err("deployment must be non-empty"); }
        if self.binding.trim().is_empty() { return Err("binding must be non-empty"); }
        if self.fault_domain.trim().is_empty() { return Err("fault_domain must be non-empty"); }
        if self.identity_digest.trim().is_empty() { return Err("identity_digest must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CouncilInvocationReceipt {
    pub model_digest: String,
    pub prompt_tokens: i64,
    pub completion_tokens: i64,
    pub latency_ms: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyCouncilReceipt {
    pub claim_digest: String,
    pub packet_digest: String,
    pub policy_digest: String,
    pub prompt_digest: String,
    pub schema_digest: String,
    pub ontology_release: String,
    pub models: String,
    pub model_digests: String,
    pub initial_vote_digests: String,
    pub revised_vote_digests: Vec<String>,
    pub disputed_fields: Vec<String>,
    pub outcome: CouncilOutcome,
    pub reason_codes: Vec<String>,
    pub rounds: i64,
    pub initial_invocations: String,
    pub revised_invocations: Vec<CouncilInvocationReceipt>,
}

pub const DIGEST: &str = "^[a-f0-9]{64}$";
pub const PROPERTY: &str = "^[a-z][a-z0-9_]{0,63}$";
pub const PUBLIC_EXPORTS: &[&str] = &["CouncilInvocationReceipt", "CouncilModelReceipt", "CouncilOutcome", "OntologyCouncilReceipt"];
