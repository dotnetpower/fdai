#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProcessApprovalProjectionError {
    pub message: String,
}

impl ProcessApprovalProjectionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ProcessApprovalProjectionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ProcessApprovalProjectionError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn project_approval_requirements(mut approval: Option<std::collections::BTreeMap<String, String>>, mut process_id: String, mut step_id: String, mut attempt: i64, mut requester: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let Some(mut approval) = approval.clone() else { return Err("Durable approval state is unavailable"); };
    if ((text(approval.clone(), String::from("process_id")).unwrap_or_else(|_| String::new())) != (process_id.clone())) || (((text(approval.clone(), String::from("step_id")).unwrap_or_else(|_| String::new())) != (step_id.clone())) || (((integer(approval.clone(), String::from("attempt"), Some(1_i64)).unwrap_or_else(|_| 0_i64)) != (attempt)) || ((normalize(text(approval.clone(), String::from("requester_principal")).unwrap_or_else(|_| String::new()))) != (normalize(requester.clone()))))) {
        return Err("Durable approval identity is inconsistent");
    }
    let role: String = text(approval.clone(), String::from("required_role")).unwrap_or_else(|_| String::new());
    let quorum: i64 = integer(approval.clone(), String::from("quorum"), None).unwrap_or_else(|_| 0_i64);
    let no_self_approval: bool = boolean(approval.clone(), String::from("no_self_approval"), true).unwrap_or_else(|_| false);
    let timeout: i64 = integer(approval.clone(), String::from("timeout_seconds"), None).unwrap_or_else(|_| 0_i64);
    let approval_revision: i64 = integer(approval.clone(), String::from("revision"), None).unwrap_or_else(|_| 0_i64);
    let expires_at: String = timestamp(String::new(), String::from("approval expires_at")).unwrap_or_else(|_| String::new());
    let mut state: String = text(approval.clone(), String::from("state")).unwrap_or_else(|_| String::new());
    let mut approved: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut rejected: bool = false;
    if rejected {
        state = String::from("rejected");
    }
    Ok(std::collections::BTreeMap::from([(String::from("approval_role"), role.clone()), (String::from("quorum"), String::new()), (String::from("no_self_approval"), String::new()), (String::from("timeout_seconds"), String::new()), (String::from("approval_revision"), String::new()), (String::from("deadline_at"), String::new()), (String::from("decision"), state.clone()), (String::from("approved_count"), String::new()), (String::from("remaining_quorum"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn mapping(mut value: String, mut label: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !(false) {
        return Err("label is unavailable or malformed");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let result: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if (!(true)) || ((((result.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
        return Err("key is unavailable or malformed");
    }
    Ok((result.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn integer(mut value: std::collections::BTreeMap<String, String>, mut key: String, mut default: Option<i64>) -> Result<i64, &'static str> {
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn boolean(mut value: std::collections::BTreeMap<String, String>, mut key: String, mut default: bool) -> Result<bool, &'static str> {
    Ok(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn timestamp(mut value: String, mut label: String) -> Result<String, &'static str> {
    if !(true) {
        return Err("label is unavailable or malformed");
    }
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn normalize(mut value: String) -> String {
    (value.trim().to_string()).to_lowercase()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProcessApprovalProjectionError", "project_approval_requirements"];
