use std::collections::BTreeMap;
pub const MAX_CONFIG_BYTES: i64 = 262144;
pub const MAX_CONFIG_BINDINGS: i64 = 64;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertNoiseScopeConfig {
    pub subscription_id: String,
    pub resource_group: String,
    pub tenant_ref: String,
    pub scope_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertNoiseWriterConfig {
    pub scope_ref: String,
    pub executor_ref: String,
    pub repository_ref: String,
    pub repository_revision: String,
    pub verification_trust_anchor_id: String,
    pub provider_conditional_updates: bool,
    pub full_authority_development_scope: bool,
    pub principal_refs: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertNoiseConfig {
    pub scopes: BTreeMap<String, AlertNoiseScopeConfig>,
    #[allow(clippy::type_complexity)]
    pub principal_scopes: BTreeMap<String, Vec<String>>,
    pub requester_subjects: BTreeMap<String, String>,
    pub writers: BTreeMap<String, AlertNoiseWriterConfig>,
    pub source_revision: Option<String>,
}

pub const SCOPE_BINDINGS_ENV: &str = "FDAI_ALERT_NOISE_SCOPE_BINDINGS_JSON";
pub const PRINCIPAL_SCOPES_ENV: &str = "FDAI_ALERT_NOISE_PRINCIPAL_SCOPES_JSON";
pub const WRITER_BINDINGS_ENV: &str = "FDAI_ALERT_NOISE_WRITER_BINDINGS_JSON";
pub const SOURCE_REVISION_ENV: &str = "FDAI_SOURCE_REVISION";
pub const REF: &str = "[a-z][a-z0-9_.:-]{0,159}";
pub const PRINCIPAL: &str = "principal:[a-f0-9]{64}";
pub const TRUST_ANCHOR: &str = "[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,511}";
pub const COMMIT: &str = "(?:commit:)?([a-f0-9]{40}(?:[a-f0-9]{24})?)";
pub const SCOPE_FIELDS: &[&str] = &["subscription_id", "resource_group", "tenant_ref", "scope_ref"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn alert_requester_ref(mut subject: String, mut scope_ref: String) -> String {
    if subject.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parse_alert_noise_config(mut environment: std::collections::BTreeMap<String, String>) -> Result<Option<AlertNoiseConfig>, &'static str> {
    if (!((environment.clone()).contains_key(SCOPE_BINDINGS_ENV))) || (!((environment.clone()).contains_key(PRINCIPAL_SCOPES_ENV))) {
        return Err("alert noise composition requires both scope and principal bindings");
    }
    let scopes: std::collections::BTreeMap<String, AlertNoiseScopeConfig> = scopes(json_setting(environment.clone(), String::from(SCOPE_BINDINGS_ENV)).unwrap_or_else(|_| String::new())).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let principals: std::collections::BTreeMap<String, std::collections::BTreeSet<String>> = principal_scopes(json_setting(environment.clone(), String::from(PRINCIPAL_SCOPES_ENV)).unwrap_or_else(|_| String::new()), scopes.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let revision: Option<String> = if (environment.clone()).contains_key(SOURCE_REVISION_ENV) { Some(commit(String::new()).unwrap_or_else(|_| String::new())) } else { None };
    Ok(Some(AlertNoiseConfig { source_revision: revision.clone(), ..Default::default() }))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn json_setting(mut environment: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    if environment.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn unique_object(mut pairs: Vec<(String, String)>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn reject_constant(mut value: String) -> Result<(), &'static str> {
    Err("non-finite alert configuration value")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn object(mut value: String, mut fields: Option<std::collections::BTreeSet<String>>, mut maximum: i64) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn array(mut value: String, mut allow_empty: bool) -> Result<Vec<String>, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn reference(mut value: String, mut pattern: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bool(mut value: String) -> Result<bool, &'static str> {
    Ok(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn oid(mut value: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn commit(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn scopes(mut value: String) -> Result<std::collections::BTreeMap<String, AlertNoiseScopeConfig>, &'static str> {
    let mut scopes: std::collections::BTreeMap<String, AlertNoiseScopeConfig> = std::collections::BTreeMap::<String, AlertNoiseScopeConfig>::new();
    let mut native: std::collections::BTreeSet<(String, String)> = std::collections::BTreeSet::<(String, String)>::new();
    let mut tenants: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    for item in array(value.clone(), false).unwrap_or_else(|_| Vec::new()) {
        let row: std::collections::BTreeMap<String, String> = object(item.clone(), None, 0_i64).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let subscription: String = oid(String::new()).unwrap_or_else(|_| String::new());
        let group: String = reference(String::new(), String::new()).unwrap_or_else(|_| String::new());
        if (group.clone()).ends_with(".") {
            return Err("alert native resource group MUST NOT end with a dot");
        }
    }
    Ok(scopes.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn principal_scopes(mut value: String, mut scopes: std::collections::BTreeMap<String, AlertNoiseScopeConfig>) -> Result<std::collections::BTreeMap<String, std::collections::BTreeSet<String>>, &'static str> {
    let mut result: std::collections::BTreeMap<String, std::collections::BTreeSet<String>> = std::collections::BTreeMap::<String, std::collections::BTreeSet<String>>::new();
    for (subject, items) in object(value.clone(), None, 1000_i64).unwrap_or_else(|_| std::collections::BTreeMap::new()) {
        let _ = oid(subject.clone()).unwrap_or_else(|_| String::new());
    }
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn writers(mut value: String, mut scopes: std::collections::BTreeMap<String, AlertNoiseScopeConfig>, mut principal_scopes: std::collections::BTreeMap<String, std::collections::BTreeSet<String>>) -> Result<std::collections::BTreeMap<String, AlertNoiseWriterConfig>, &'static str> {
    let mut writers: std::collections::BTreeMap<String, AlertNoiseWriterConfig> = std::collections::BTreeMap::<String, AlertNoiseWriterConfig>::new();
    for item in array(value.clone(), false).unwrap_or_else(|_| Vec::new()) {
        let row: std::collections::BTreeMap<String, String> = object(item.clone(), None, 0_i64).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let scope: String = reference(String::new(), String::new()).unwrap_or_else(|_| String::new());
        if (!((scopes.clone()).contains_key(scope.as_str()))) || ((writers.clone()).contains_key(scope.as_str())) {
            return Err("alert writer scopes contain duplicate or unbound routes");
        }
        let executor: String = reference(String::new(), String::from(PRINCIPAL)).unwrap_or_else(|_| String::new());
        writers.insert(scope.clone(), AlertNoiseWriterConfig { scope_ref: scope.clone(), executor_ref: executor.clone(), repository_ref: reference(String::new(), String::new()).unwrap_or_else(|_| String::new()), repository_revision: commit(String::new()).unwrap_or_else(|_| String::new()), verification_trust_anchor_id: reference(String::new(), String::from(TRUST_ANCHOR)).unwrap_or_else(|_| String::new()), provider_conditional_updates: bool(String::new()).unwrap_or_else(|_| false), full_authority_development_scope: bool(String::new()).unwrap_or_else(|_| false), ..Default::default() });
    }
    Ok(writers.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AlertNoiseConfig", "AlertNoiseScopeConfig", "AlertNoiseWriterConfig", "alert_requester_ref", "parse_alert_noise_config"];
