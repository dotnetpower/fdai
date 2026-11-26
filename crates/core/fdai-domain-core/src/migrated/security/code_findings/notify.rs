pub const ALERT_CATEGORY: &str = "code_security_operational_alert";
pub const DIGEST_CATEGORY: &str = "digest_code_security_findings_daily";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NotificationPlanError {
    pub message: String,
}

impl NotificationPlanError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for NotificationPlanError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for NotificationPlanError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn params(mut package: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::from([(String::from("repository"), String::new()), (String::from("revision"), String::new()), (String::from("total"), String::new()), (String::from("urgent"), String::new()), (String::from("p0"), String::new()), (String::from("p1"), String::new()), (String::from("p2"), String::new()), (String::from("p3"), String::new()), (String::from("p4"), String::new()), (String::from("critical"), String::new()), (String::from("high"), String::new()), (String::from("medium"), String::new()), (String::from("low"), String::new()), (String::from("undetermined"), String::new()), (String::from("hypothesis"), String::new()), (String::from("kev"), String::new()), (String::from("exposure"), String::new()), (String::from("coverage"), String::from("yes\" if package[\"coverage_complete\"] else \"no"))]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn message(mut category: String, mut tier: String, mut template_key: String, mut params: std::collections::BTreeMap<String, String>, mut severity: String, mut correlation_id: String, mut catalog: String) -> String {
    if category.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn plan_code_security_notifications(mut raw_package: std::collections::BTreeMap<String, String>, mut routes: Vec<String>, mut catalog: Option<String>) -> Result<Vec<String>, &'static str> {
    let params: std::collections::BTreeMap<String, String> = params(std::collections::BTreeMap::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let mut messages: Vec<String> = Vec::<String>::new();
    Ok(messages.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ALERT_CATEGORY", "DIGEST_CATEGORY", "NotificationPlanError", "plan_code_security_notifications"];
