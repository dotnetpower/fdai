#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SafeguardCoordinationDisposition {
    #[default]
    Completed,
    Duplicate,
    Quarantined,
    Blocked,
}

impl SafeguardCoordinationDisposition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Completed => "completed",
            Self::Duplicate => "duplicate",
            Self::Quarantined => "quarantined",
            Self::Blocked => "blocked",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SafeguardCoordinatedDispatchResult {
    pub disposition: SafeguardCoordinationDisposition,
    pub bundle_digest: Option<String>,
    pub lifecycle: Option<String>,
    pub closure_receipt: Option<String>,
    pub dispatch_performed: bool,
    pub reason: Option<String>,
    pub execution_authority: bool,
    pub effect_verification_authority: bool,
}

impl SafeguardCoordinatedDispatchResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.effect_verification_authority { return Err("effect_verification_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SafeguardLifecycleCoordinatorConfig {
    pub source_revision: String,
    pub producer_id: String,
    pub producer_version: String,
    pub actor: String,
    pub expected_lock_verifier_id: String,
    pub expected_lock_verifier_version: String,
    pub expected_lock_trust_anchor_id: String,
    pub reservation_lease: String,
    pub production: bool,
}

impl SafeguardLifecycleCoordinatorConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.source_revision.trim().is_empty() { return Err("source_revision must be non-empty"); }
        if self.producer_id.trim().is_empty() { return Err("producer_id must be non-empty"); }
        if self.producer_version.trim().is_empty() { return Err("producer_version must be non-empty"); }
        if self.actor.trim().is_empty() { return Err("actor must be non-empty"); }
        if self.expected_lock_verifier_id.trim().is_empty() { return Err("expected_lock_verifier_id must be non-empty"); }
        if self.expected_lock_verifier_version.trim().is_empty() { return Err("expected_lock_verifier_version must be non-empty"); }
        if self.expected_lock_trust_anchor_id.trim().is_empty() { return Err("expected_lock_trust_anchor_id must be non-empty"); }
        if self.reservation_lease.trim().is_empty() { return Err("reservation_lease must be non-empty"); }
        Ok(())
    }
}

pub const SOURCE_REVISION: &str = "^commit:[a-f0-9]{40}(?:[a-f0-9]{24})?$";
pub trait ProductionSafeguardStore {
    fn production_eligible(&self) -> bool;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SafeguardCoordinationError {
    pub message: String,
}

impl SafeguardCoordinationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SafeguardCoordinationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SafeguardCoordinationError {}

pub const PUBLIC_EXPORTS: &[&str] = &["ProductionSafeguardStore", "SafeguardCoordinatedDispatchResult", "SafeguardCoordinationDisposition", "SafeguardCoordinationError", "SafeguardLifecycleCoordinatorConfig"];
