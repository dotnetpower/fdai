use std::collections::BTreeMap;
pub const MAX_REGISTRY_BYTES: i64 = 262144;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RevisionClass {
    #[default]
    RoutineRotation,
    Revocation,
}

impl RevisionClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::RoutineRotation => "routine_rotation",
            Self::Revocation => "revocation",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TrackedDict {
    pub duplicates: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ValidityWindow {
    pub valid_from: String,
    pub valid_until: String,
    pub revoked: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CaseScope {
    pub case_scope_id: String,
    pub access_scope_digest: String,
    pub resource_selectors: Vec<String>,
    pub purposes: Vec<String>,
    pub policy_revision: String,
    pub window: Box<ValidityWindow>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PrincipalGrant {
    pub grant_id: String,
    pub selector_kind: String,
    pub selector_value: String,
    pub case_scopes: Vec<String>,
    pub operations: Vec<String>,
    pub purposes: Vec<String>,
    pub reviewer: String,
    pub window: Box<ValidityWindow>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReuseGrant {
    pub grant_id: String,
    pub case_scopes: Vec<String>,
    pub target_scope_digest: String,
    pub window: Box<ValidityWindow>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GrantDecision {
    pub allowed: bool,
    pub rejection_class: Option<String>,
    pub reasons: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub case_scope: Option<Box<CaseScope>>,
    pub matched_grants: Vec<String>,
    pub conflicts: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CaseScopeGrantRegistry {
    pub pin: String,
    pub revision: i64,
    pub case_scopes: BTreeMap<String, CaseScope>,
    pub principal_grants: Vec<PrincipalGrant>,
    pub reuse_grants: Vec<ReuseGrant>,
}

pub const GRANT_REGISTRY_ID: &str = "fdai.operational-evidence.case-scope-grants";
pub const SCOPE_DIGEST: &str = "^[a-f0-9]{64}$";
pub const WINDOW_FIELDS: &[&str] = &["valid_from", "valid_until", "revoked"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RegistryUnavailableError {
    pub message: String,
}

impl RegistryUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for RegistryUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for RegistryUnavailableError {}

impl ValidityWindow {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn active_at(&self, mut evaluated_at: String) -> bool {
        (!(self.revoked)) && (((self.valid_from.clone()) <= (evaluated_at.clone())) && ((evaluated_at.clone()) < (self.valid_until.clone())))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn narrowed_by(&self, mut current: ValidityWindow) -> bool {
        ((current.revoked) && (!(self.revoked))) || (((current.valid_from.clone()) > (self.valid_from.clone())) || ((current.valid_until.clone()) < (self.valid_until.clone())))
    }
}

impl CaseScope {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn contains(&self, mut target_ref: String) -> bool {
        let target: String = target_ref.to_lowercase();
        for selector in self.resource_selectors.clone() {
            let value: String = (selector.clone()).to_lowercase();
            if (value.clone()).ends_with("/*") {
                if ((target.clone()).starts_with(((value.clone()).chars().take((-1_i64).max(0) as usize).collect::<String>()).as_str())) && ((((target.clone()).len() as i64)) > ((((value.clone()).len() as i64)).saturating_sub(1_i64))) {
                    return true;
                }
            } else if (target.clone()) == (value.clone()) {
                return true;
            }
        }
        false
    }
}

impl PrincipalGrant {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn selects(&self, mut receipt: String) -> bool {
        if receipt.is_empty() {
            return false;
        }
        false
    }
}

impl GrantDecision {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn deny(mut rejection_class: String, mut reason: String, mut case_scope: Option<CaseScope>) -> GrantDecision {
        if rejection_class.is_empty() {
            return Default::default();
        }
        Default::default()
    }
}

impl CaseScopeGrantRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn scope_for(&self, mut access_scope_digest: String) -> Option<CaseScope> {
        if access_scope_digest.is_empty() {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::too_many_arguments)]
    pub fn authorize(&self, mut receipt: String, mut access_scope_digest: String, mut operation: String, mut purpose_id: String, mut at: String, mut target_ref: Option<String>, mut policy_revision: Option<String>) -> GrantDecision {
        let scope: Option<CaseScope> = self.scope_for(access_scope_digest.clone());
        let scope_decision: Option<GrantDecision> = scope_current(Default::default(), at.clone());
        if let Some(mut scope_decision) = scope_decision.clone() {
            return scope_decision.clone();
        }
        single_grant_decision(Vec::new(), Default::default(), at.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn authorize_reuse(&self, mut case_scope_digest: String, mut target_scope_digest: String, mut at: String) -> GrantDecision {
        let scope: Option<CaseScope> = self.scope_for(case_scope_digest.clone());
        let scope_decision: Option<GrantDecision> = scope_current(Default::default(), at.clone());
        if let Some(mut scope_decision) = scope_decision.clone() {
            return scope_decision.clone();
        }
        single_grant_decision(Vec::new(), Default::default(), at.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn entry_windows(&self) -> std::collections::BTreeMap<String, ValidityWindow> {
        std::collections::BTreeMap::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn pairs(mut pairs: Vec<(String, String)>) -> String {
    let mut duplicates: Vec<String> = Vec::<String>::new();
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn content_pin(mut data: Vec<u8>) -> String {
    if data.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_pinned_json(mut data: Vec<u8>, mut expected_pin: String, mut label: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if (!(true)) || ((((data.clone()).len() as i64)) > (MAX_REGISTRY_BYTES)) {
        return Err("label MUST be bounded bytes");
    }
    if (content_pin(data.clone())) != (expected_pin.clone()) {
        return Err("label content does not match its reviewed pin");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn has_duplicates(mut value: String) -> bool {
    if value.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn exact_fields(mut value: String, mut required: std::collections::BTreeSet<String>, mut label: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !(false) {
        return Err("label MUST be an object");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bounded_text(mut value: String, mut label: String, mut maximum: i64) -> Result<String, &'static str> {
    if (!(true)) || (((value.trim().to_string()).is_empty()) || ((((value.clone()).len() as i64)) > (maximum))) {
        return Err("label MUST be bounded non-empty text");
    }
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn text_tuple(mut value: String, mut label: String, mut maximum: i64) -> Result<Vec<String>, &'static str> {
    if (!(false)) || (!(((1_i64) <= (((value.clone()).len() as i64))) && ((((value.clone()).len() as i64)) <= (maximum)))) {
        return Err("label MUST be a bounded non-empty array");
    }
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn aware_time(mut value: String, mut label: String) -> Result<String, &'static str> {
    let text: String = bounded_text(value.clone(), label.clone(), 64_i64).unwrap_or_else(|_| String::new());
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn strict_bool(mut value: String, mut label: String) -> Result<bool, &'static str> {
    Ok(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn positive_int(mut value: String, mut label: String, mut maximum: i64) -> Result<i64, &'static str> {
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn validity(mut raw: std::collections::BTreeMap<String, String>, mut label: String) -> ValidityWindow {
    ValidityWindow { valid_from: aware_time(String::new(), format!("{}.valid_from", label.clone())).unwrap_or_else(|_| String::new()), valid_until: aware_time(String::new(), format!("{}.valid_until", label.clone())).unwrap_or_else(|_| String::new()), revoked: strict_bool(String::new(), format!("{}.revoked", label.clone())).unwrap_or_else(|_| false), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn scope_current(mut scope: CaseScope, mut at: String) -> Option<GrantDecision> {
    if at.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn single_grant_decision(mut matching: Vec<String>, mut scope: CaseScope, mut at: String) -> GrantDecision {
    let grants: Vec<String> = matching.clone();
    GrantDecision { case_scope: Some(Box::new(scope.clone())), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_grant_registry(mut data: Vec<u8>, mut expected_pin: String) -> Result<CaseScopeGrantRegistry, &'static str> {
    let raw: std::collections::BTreeMap<String, String> = load_pinned_json(data.clone(), expected_pin.clone(), String::from("case-scope grant registry")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    if has_duplicates(String::new()) {
        return Err("case-scope grant registry repeats a key");
    }
    let top: std::collections::BTreeMap<String, String> = exact_fields(String::new(), std::collections::BTreeSet::new(), String::from("case-scope grant registry")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let revision: i64 = positive_int(String::new(), String::from("grant registry revision"), 0_i64).unwrap_or_else(|_| 0_i64);
    let _ = unique(Vec::new(), String::from("case_scope_id")).unwrap_or_else(|_| ());
    let _ = unique(Vec::new(), String::from("access_scope_digest")).unwrap_or_else(|_| ());
    let _ = unique(Vec::new(), String::from("grant_id")).unwrap_or_else(|_| ());
    Ok(CaseScopeGrantRegistry { pin: expected_pin.clone(), revision: revision, ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn classify_grant_revision(mut previous: CaseScopeGrantRegistry, mut current: CaseScopeGrantRegistry) -> RevisionClass {
    let current_scopes: BTreeMap<String, CaseScope> = current.case_scopes.clone();
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn case_scope(mut raw: String) -> Result<CaseScope, &'static str> {
    let value: std::collections::BTreeMap<String, String> = exact_fields(raw.clone(), std::collections::BTreeSet::new(), String::from("case scope")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let digest: String = bounded_text(String::new(), String::from("access_scope_digest"), 0_i64).unwrap_or_else(|_| String::new());
    Ok(CaseScope { case_scope_id: bounded_text(String::new(), String::from("case_scope_id"), 128_i64).unwrap_or_else(|_| String::new()), access_scope_digest: digest.clone(), resource_selectors: text_tuple(String::new(), String::from("resource_selectors"), 0_i64).unwrap_or_else(|_| Vec::new()), policy_revision: bounded_text(String::new(), String::from("policy_revision"), 0_i64).unwrap_or_else(|_| String::new()), window: Box::new(validity(value.clone(), String::from("case scope"))), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn principal_grant(mut raw: String) -> Result<PrincipalGrant, &'static str> {
    let value: std::collections::BTreeMap<String, String> = exact_fields(raw.clone(), std::collections::BTreeSet::new(), String::from("principal grant")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let selector: std::collections::BTreeMap<String, String> = exact_fields(String::new(), std::collections::BTreeSet::from([String::from("kind"), String::from("value")]), String::from("selector")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let operations: std::collections::BTreeSet<String> = (text_tuple(String::new(), String::from("operations"), 4_i64).unwrap_or_else(|_| Vec::new())).into_iter().collect::<std::collections::BTreeSet<String>>();
    Ok(PrincipalGrant { grant_id: bounded_text(String::new(), String::from("grant_id"), 128_i64).unwrap_or_else(|_| String::new()), selector_value: bounded_text(String::new(), String::from("selector value"), 256_i64).unwrap_or_else(|_| String::new()), reviewer: bounded_text(String::new(), String::from("reviewer"), 256_i64).unwrap_or_else(|_| String::new()), window: Box::new(validity(value.clone(), String::from("principal grant"))), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn reuse_grant(mut raw: String) -> Result<ReuseGrant, &'static str> {
    let value: std::collections::BTreeMap<String, String> = exact_fields(raw.clone(), std::collections::BTreeSet::new(), String::from("reuse grant")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let target: String = bounded_text(String::new(), String::from("target_scope_digest"), 0_i64).unwrap_or_else(|_| String::new());
    Ok(ReuseGrant { grant_id: bounded_text(String::new(), String::from("grant_id"), 128_i64).unwrap_or_else(|_| String::new()), target_scope_digest: target.clone(), window: Box::new(validity(value.clone(), String::from("reuse grant"))), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn purposes(mut value: String) -> Result<std::collections::BTreeSet<String>, &'static str> {
    let purposes: std::collections::BTreeSet<String> = (text_tuple(value.clone(), String::from("purposes"), 16_i64).unwrap_or_else(|_| Vec::new())).into_iter().collect::<std::collections::BTreeSet<String>>();
    Ok(purposes.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn list(mut value: String, mut label: String, mut minimum: i64) -> Result<Vec<String>, &'static str> {
    if (!(false)) || (!(((minimum) <= (((value.clone()).len() as i64))) && ((((value.clone()).len() as i64)) <= (256_i64)))) {
        return Err("label MUST be a bounded array");
    }
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn unique(mut values: Vec<String>, mut label: String) -> Result<(), &'static str> {
    let items: Vec<String> = list(String::new(), String::new(), 0_i64).unwrap_or_else(|_| Vec::new());
    if ((((items.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((items.clone()).len() as i64)) {
        return Err("label MUST be unique");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["GRANT_OPERATIONS", "GRANT_REGISTRY_ID", "CaseScope", "CaseScopeGrantRegistry", "GrantDecision", "PrincipalGrant", "RegistryUnavailableError", "ReuseGrant", "RevisionClass", "ValidityWindow", "classify_grant_revision", "content_pin", "load_grant_registry"];
