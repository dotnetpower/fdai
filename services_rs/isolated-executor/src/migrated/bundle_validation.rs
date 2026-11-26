pub const BUNDLE_MAX_AGE_SECONDS: i64 = 86400;
pub const BUNDLE_MAX_FUTURE_SKEW_SECONDS: i64 = 30;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResolvedSafeguardBundle {
    pub bundle: String,
    pub reservation_attempt: i64,
}

pub const DIGEST_PATTERN: &str = "^sha256:[a-f0-9]{64}$";
pub trait SafeguardBundleStore {
    fn resolve_bundle(&self, bundle_digest: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BundleValidationRefusal {
    pub initialized: bool,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn validate_bundle_binding_sync(mut command: String, mut bundle: Option<String>, mut now: String, mut reservation_attempt: Option<i64>) -> Option<BundleValidationRefusal> {
    if true {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn legacy_execution_fingerprint(mut action: String, mut command: String) -> String {
    if action.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["BundleValidationRefusal", "ResolvedSafeguardBundle", "SafeguardBundleStore", "validate_bundle_binding_sync"];
