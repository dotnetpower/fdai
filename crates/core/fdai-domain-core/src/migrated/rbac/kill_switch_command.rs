pub const MIN_REASON_CHARS: i64 = 20;
pub const MAX_REASON_CHARS: i64 = 500;
pub const MAX_REQUEST_ID_CHARS: i64 = 200;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct KillSwitchState {
    pub engaged: bool,
    pub revision: i64,
    pub updated_at: String,
    pub updated_by: String,
    pub reason: String,
    pub request_id: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct KillSwitchCommandService {
    pub store: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct KillSwitchCommandError {
    pub message: String,
}

impl KillSwitchCommandError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for KillSwitchCommandError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for KillSwitchCommandError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct KillSwitchCommandConflictError {
    pub message: String,
}

impl KillSwitchCommandConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for KillSwitchCommandConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for KillSwitchCommandConflictError {}

impl KillSwitchState {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("engaged"), String::new()), (String::from("revision"), String::new()), (String::from("updated_at"), String::new()), (String::from("updated_by"), self.updated_by.clone()), (String::from("reason"), self.reason.clone()), (String::from("request_id"), self.request_id.clone())])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<KillSwitchState, &'static str> {
        let engaged: Option<String> = (raw.clone()).get("engaged").cloned();
        let revision: Option<String> = (raw.clone()).get("revision").cloned();
        let updated_at: Option<String> = (raw.clone()).get("updated_at").cloned();
        let updated_by: String = required_state_text(raw.clone(), String::from("updated_by")).unwrap_or_else(|_| String::new());
        let reason: String = required_state_text(raw.clone(), String::from("reason")).unwrap_or_else(|_| String::new());
        let request_id: String = required_state_text(raw.clone(), String::from("request_id")).unwrap_or_else(|_| String::new());
        if !(true) {
            return Err("kill-switch engaged MUST be a boolean");
        }
        if (!(true)) || (!((updated_at.clone()).is_some())) {
            return Err("kill-switch state updated_at is incomplete");
        }
        Err("runtime_binding_required")
    }
}

impl KillSwitchCommandService {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn set_state(&self, mut engaged: bool, mut actor_oid: String, mut reason: String, mut request_id: String, mut now: Option<String>) -> Result<KillSwitchState, &'static str> {
        let normalized_actor: String = bounded_text(actor_oid.clone(), String::from("actor_oid"), 1_i64, 0_i64).unwrap_or_else(|_| String::new());
        let normalized_reason: String = bounded_text(reason.clone(), String::from("reason"), MIN_REASON_CHARS, MAX_REASON_CHARS).unwrap_or_else(|_| String::new());
        let normalized_request: String = bounded_text(request_id.clone(), String::from("request_id"), 1_i64, MAX_REQUEST_ID_CHARS).unwrap_or_else(|_| String::new());
        let updated: KillSwitchState = KillSwitchState { engaged: engaged, updated_by: normalized_actor.clone(), reason: normalized_reason.clone(), request_id: normalized_request.clone(), ..Default::default() };
        let audit_entry: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("event_id"), String::new()), (String::from("correlation_id"), normalized_request.clone()), (String::from("actor"), normalized_actor.clone()), (String::from("action_kind"), if engaged { String::from("system.kill-switch.engaged") } else { String::from("system.kill-switch.disengaged") }), (String::from("mode"), String::from("enforce")), (String::from("decision"), if engaged { String::from("engaged") } else { String::from("disengaged") }), (String::from("idempotency_key"), normalized_request.clone()), (String::from("revision"), String::new()), (String::from("reason"), normalized_reason.clone()), (String::from("timestamp"), String::new())]);
        Err("kill-switch state changed concurrently retry with a new request_id")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bounded_text(mut value: String, mut name: String, mut minimum: i64, mut maximum: i64) -> Result<String, &'static str> {
    let normalized: String = value.trim().to_string();
    if (((normalized.clone()).len() as i64)) < (minimum) {
        return Err("name MUST be at least minimum characters");
    }
    if (((normalized.clone()).len() as i64)) > (maximum) {
        return Err("name MUST be at most maximum characters");
    }
    Ok(normalized.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required_state_text(mut raw: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    let value: Option<String> = (raw.clone()).get(name.as_str()).cloned();
    if (!(true)) || (!((value.clone()).is_some())) {
        return Err("kill-switch state name is incomplete");
    }
    Ok((value.clone()).unwrap_or_default())
}

pub const PUBLIC_EXPORTS: &[&str] = &["KillSwitchCommandConflictError", "KillSwitchCommandError", "KillSwitchCommandService", "KillSwitchState"];
