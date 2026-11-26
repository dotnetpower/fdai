pub mod access_grants;
pub mod assignments;
pub mod break_glass;
pub mod capabilities;
pub mod contracts;
pub mod errors;
pub mod governance;
pub mod handover;
pub mod handover_acceptance;
pub mod handover_command_guard;
pub mod handover_contribution;
pub mod handover_postgres;
pub mod handover_review_eligibility;
pub mod handover_runtime;
pub mod handover_session_budget;
pub mod handover_state;
pub mod hil_bootstrap_canary;
pub mod hil_callback;
pub mod hil_callback_audit;
pub mod hil_callback_authority;
pub mod hil_callback_context;
pub mod hil_callback_decision;
pub mod hil_callback_validation;
pub mod hil_decision_outbox;
pub mod hil_development_approval;
pub mod hil_operator_decision;
pub mod hil_teams_callback;
pub mod http;
pub mod iam_routes;
pub mod manifest;
pub mod notification_receipt;
pub mod pkg_init;
pub mod policy_administration;
pub mod report_line_contact;
pub mod report_line_contact_outbox;
pub mod report_lines;
pub mod scoped_duties;
pub mod scoped_duty_contracts;
pub mod settings;
pub mod slack_handoff;

#[must_use]
pub fn build_migrated_router() -> fdai_contracts::http_compat::Router {
    fdai_contracts::http_compat::Router::new()
        .merge(access_grants::build_axum_router())
        .merge(assignments::build_axum_router())
        .merge(governance::build_axum_router())
        .merge(handover::build_axum_router())
        .merge(hil_callback::build_axum_router())
        .merge(hil_operator_decision::build_axum_router())
        .merge(hil_teams_callback::build_axum_router())
        .merge(iam_routes::build_axum_router())
        .merge(policy_administration::build_axum_router())
        .merge(report_line_contact::build_axum_router())
        .merge(report_lines::build_axum_router())
        .merge(scoped_duties::build_axum_router())
        .merge(settings::build_axum_router())
        .merge(slack_handoff::build_axum_router())
}
