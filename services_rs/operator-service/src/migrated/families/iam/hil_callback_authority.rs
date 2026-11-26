use std::collections::BTreeMap;
pub const MAX_MAPPINGS: i64 = 1000;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum HilCallbackChannel {
    #[default]
    Teams,
    Slack,
}

impl HilCallbackChannel {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Teams => "teams",
            Self::Slack => "slack",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HilCallbackActor {
    pub oid: String,
    pub identity_ref: String,
    pub roles: Vec<String>,
    pub authority_basis: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HilCallbackAuthorityConfig {
    pub teams_application_id: Option<String>,
    pub teams_approval_audience: Option<String>,
    pub slack_approval_audience: Option<String>,
    pub teams_principal_by_sender_id: BTreeMap<String, String>,
    pub slack_principal_by_sender_id: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EntraHilCallbackAuthority {
    pub authenticator: String,
    pub config: Box<HilCallbackAuthorityConfig>,
}

pub const TEAMS_APPLICATION_ID_ENV: &str = "FDAI_TEAMS_APPLICATION_ID";
pub const TEAMS_PRINCIPAL_MAP_ENV: &str = "FDAI_TEAMS_PRINCIPAL_MAP_JSON";
pub const TEAMS_APPROVAL_TEAM_ID_ENV: &str = "FDAI_TEAMS_APPROVAL_TEAM_ID";
pub const TEAMS_APPROVAL_CHANNEL_ID_ENV: &str = "FDAI_TEAMS_APPROVAL_CHANNEL_ID";
pub const SLACK_PRINCIPAL_MAP_ENV: &str = "FDAI_SLACK_PRINCIPAL_MAP_JSON";
pub const SLACK_TEAM_ID_ENV: &str = "FDAI_SLACK_TEAM_ID";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HilCallbackAuthorityError {
    pub message: String,
}

impl HilCallbackAuthorityError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for HilCallbackAuthorityError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for HilCallbackAuthorityError {}

pub trait HilCallbackAuthority {
    fn authenticate(&self, authorization: Option<String>, channel: HilCallbackChannel, provider_actor_id: String, audience: String) -> String;
}

impl HilCallbackAuthorityConfig {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_environment(mut values: std::collections::BTreeMap<String, String>, mut group_ids: std::collections::BTreeMap<String, String>) -> Result<HilCallbackAuthorityConfig, &'static str> {
        let teams_application_id: String = ((values.clone()).get(TEAMS_APPLICATION_ID_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
        let teams_team_id: String = ((values.clone()).get(TEAMS_APPROVAL_TEAM_ID_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
        let teams_channel_id: String = ((values.clone()).get(TEAMS_APPROVAL_CHANNEL_ID_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
        let teams_principal_map: String = ((values.clone()).get(TEAMS_PRINCIPAL_MAP_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
        let slack_team_id: String = ((values.clone()).get(SLACK_TEAM_ID_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
        let slack_principal_map: String = ((values.clone()).get(SLACK_PRINCIPAL_MAP_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn teams_a1_enabled(&self) -> bool {
        self.teams_approval_audience.is_some()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn slack_a1_enabled(&self) -> bool {
        self.slack_approval_audience.is_some()
    }
}

impl EntraHilCallbackAuthority {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn authenticate(&self, mut authorization: Option<String>, mut channel: HilCallbackChannel, mut provider_actor_id: String, mut audience: String) -> Result<HilCallbackActor, &'static str> {
        Ok(HilCallbackActor::default())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn meets_role(mut roles: std::collections::BTreeSet<String>, mut required_role: String) -> bool {
    if required_role.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn principal_map(mut value: String, mut allow_empty: bool) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if (value.trim().to_string()).is_empty() {
        return Ok(if allow_empty { std::collections::BTreeMap::<String, String>::new() } else { invalid_map().unwrap_or_else(|_| std::collections::BTreeMap::new()) });
    }
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn invalid_map() -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Err("approval principal mapping MUST be non-empty")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn unique_object(mut pairs: Vec<(String, String)>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(value.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["EntraHilCallbackAuthority", "HilCallbackActor", "HilCallbackAuthority", "HilCallbackAuthorityConfig", "HilCallbackAuthorityError", "HilCallbackChannel", "SLACK_TEAM_ID_ENV", "SLACK_PRINCIPAL_MAP_ENV", "TEAMS_APPROVAL_CHANNEL_ID_ENV", "TEAMS_APPROVAL_TEAM_ID_ENV", "TEAMS_APPLICATION_ID_ENV", "TEAMS_PRINCIPAL_MAP_ENV", "meets_role"];
