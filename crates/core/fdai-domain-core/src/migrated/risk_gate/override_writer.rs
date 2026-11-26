use std::collections::BTreeMap;
pub const ACTION_TYPE_ID_MAX_LEN: i64 = 80;
pub const PRINCIPAL_ID_MAX_LEN: i64 = 256;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Axis {
    #[default]
    Ceiling,
    Role,
    Env,
    StaticBlast,
    LiveBlast,
}

impl Axis {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Ceiling => "ceiling",
            Self::Role => "role",
            Self::Env => "env",
            Self::StaticBlast => "static_blast",
            Self::LiveBlast => "live_blast",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TargetLevel {
    #[default]
    EnforceHil,
    ShadowOnly,
}

impl TargetLevel {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::EnforceHil => "enforce_hil",
            Self::ShadowOnly => "shadow_only",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Scope {
    #[default]
    Resource,
    ResourceGroup,
}

impl Scope {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Resource => "resource",
            Self::ResourceGroup => "resource-group",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OverrideRequest {
    pub override_id: String,
    pub action_type_id: String,
    pub axis: Axis,
    pub target_level: TargetLevel,
    pub scope: Scope,
    pub scope_ref: String,
    pub expires_at: String,
    pub justification: String,
    pub requester_id: String,
    pub approver_id: String,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RegoOverlay {
    pub path: String,
    pub content: String,
}

pub const ALLOWED_AXES: &[&str] = &["ceiling", "role", "env", "static_blast", "live_blast"];
pub const ALLOWED_SCOPES: &[&str] = &["resource", "resource-group"];
pub const ALLOWED_TARGET_LEVELS: &[&str] = &["enforce_hil", "shadow_only"];
pub const OVERRIDE_ID_PATTERN: &str = "^[a-z0-9][a-z0-9._-]{0,127}$";
pub const ONTOLOGY_ID_PATTERN: &str = "^[a-z][a-z0-9_.-]*$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OverrideWriterError {
    pub message: String,
}

impl OverrideWriterError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for OverrideWriterError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for OverrideWriterError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn render_override_rego(mut request: OverrideRequest) -> RegoOverlay {
    let _ = py_validate(request.clone()).unwrap_or_else(|_| ());
    let package: String = package_name(request.clone());
    let content: String = render(request.clone(), package.clone());
    RegoOverlay { content: content.clone(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn py_validate(mut request: OverrideRequest) -> Result<(), &'static str> {
    if (request.override_id.clone()).is_empty() {
        return Err("override_id MUST be non-empty");
    }
    if (request.action_type_id.clone()).is_empty() {
        return Err("action_type_id MUST be non-empty");
    }
    if (((request.action_type_id.clone()).len() as i64)) > (ACTION_TYPE_ID_MAX_LEN) {
        return Err("action_type_id MUST be at most _ACTION_TYPE_ID_MAX_LEN chars");
    }
    if !(is_ontology_id(request.action_type_id.clone())) {
        return Err("action_type_id request.action_type_idr MUST match a-za-z0-9_.-");
    }
    if ((request.scope_ref.clone()).trim().to_string()).is_empty() {
        return Err("scope_ref MUST be non-empty");
    }
    let _ = validate_iso_expiry(request.expires_at.clone()).unwrap_or_else(|_| ());
    if (((request.justification.clone()).len() as i64)) < (20_i64) {
        return Err("justification MUST be at least 20 chars");
    }
    if (((request.justification.clone()).len() as i64)) > (500_i64) {
        return Err("justification MUST be at most 500 chars");
    }
    if (request.requester_id.clone()).is_empty() {
        return Err("requester_id MUST be non-empty");
    }
    if (request.approver_id.clone()).is_empty() {
        return Err("approver_id MUST be non-empty");
    }
    if (((request.requester_id.clone()).trim().to_string()).to_lowercase()) == (((request.approver_id.clone()).trim().to_string()).to_lowercase()) {
        return Err("no self-approval - requester_id and approver_id MUST differ");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_iso_expiry(mut value: String) -> Result<(), &'static str> {
    if (value.clone()).is_empty() {
        return Err("expires_at MUST be non-empty");
    }
    let normalized: String = if (value.clone()).ends_with("Z") { format!("{}{}", (value.clone()).chars().take((-1_i64).max(0) as usize).collect::<String>(), String::from("+00:00")) } else { value.clone() };
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_ontology_id(mut value: String) -> bool {
    if value.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn render(mut request: OverrideRequest, mut package: String) -> String {
    if package.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn package_name(mut request: OverrideRequest) -> String {
    let at_id: String = package_slug(request.action_type_id.clone());
    let ovr_id: String = package_slug(request.override_id.clone());
    format!("fdai.action_types.{}.{}", at_id.clone(), ovr_id.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn package_slug(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn slugify(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn escape_comment(mut value: String) -> String {
    let cleaned: String = (((value.clone()).replace("\n", " ")).replace("\r", " ")).trim().to_string();
    if (((cleaned.clone()).len() as i64)) > (200_i64) {
        return format!("{}{}", (cleaned.clone()).chars().take((197_i64).max(0) as usize).collect::<String>(), String::from("..."));
    }
    cleaned.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rego_string(mut value: String) -> String {
    ((((value.clone()).replace("\\", "\\\\")).replace("\"", "\\\"")).replace("\n", "\\n")).replace("\r", "\\r")
}

pub const PUBLIC_EXPORTS: &[&str] = &["Axis", "OverrideRequest", "OverrideWriterError", "RegoOverlay", "Scope", "TargetLevel", "render_override_rego"];
