use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct IamFamilyBindings {
    pub authorize: String,
    pub authenticate: String,
    pub access_grants: Option<String>,
    pub human_access: Option<String>,
    pub directory: Option<String>,
    pub assignments: Option<String>,
    pub scoped_duties: Option<String>,
    pub reporting_lines: Option<String>,
    pub report_line_contact: Option<String>,
    pub handover_goals: Option<String>,
    pub handover_conversations: Option<String>,
    pub model_settings: Option<String>,
    pub runtime_settings: Option<String>,
    pub teams_workflow_tester: Option<String>,
    pub slack_webhook_tester: Option<String>,
    pub kill_switch_authenticator: Option<String>,
    pub kill_switch_publisher: Option<String>,
    pub kill_switch_receipt_issuer: Option<String>,
    pub break_glass: Option<String>,
    pub configuration_review: Option<String>,
    pub hil_registry: Option<String>,
    pub hil_outbox: Option<String>,
    pub hil_config: Option<String>,
    pub hil_authority: Option<String>,
    pub hil_audit: Option<String>,
    pub hil_context: Option<String>,
    pub hil_teams_normalizer: Option<String>,
    pub slack_handoff_store: Option<String>,
    pub slack_signing_secret: Option<String>,
    pub slack_authority_config: Option<String>,
    pub slack_authenticator: Option<String>,
    pub slack_console_origin: Option<String>,
    pub notification_receipt_ingress: Option<String>,
    pub policy_administration_selected: bool,
    pub policy_authenticator: Option<String>,
    pub policy_revision_publisher: Option<String>,
    pub policy_receipt_issuer: Option<String>,
    pub identity_provider: String,
    #[allow(clippy::type_complexity)]
    pub role_group_ids: Option<BTreeMap<String, String>>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn make_iam_family_routes(mut bindings: IamFamilyBindings) -> Result<Vec<String>, &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn redacting_route(mut route: String) -> String {
    if route.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["IAM_FAMILY_MANIFEST", "HilCallbackConfig", "IamFamilyBindings", "iam_family_manifest", "make_iam_family_routes"];
