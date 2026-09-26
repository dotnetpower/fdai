"""Exact method, path, and route-name manifest for the IAM route family."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IamRouteManifestEntry:
    """One frozen public route owned by the IAM family."""

    method: str
    path: str
    name: str


IAM_FAMILY_MANIFEST = (
    IamRouteManifestEntry("POST", "/access-grants/{request_id:str}/decision", "handler"),
    IamRouteManifestEntry("GET", "/access-grants/stream", "handler"),
    IamRouteManifestEntry("GET", "/iam", "get_iam"),
    IamRouteManifestEntry("GET", "/iam/self", "get_self"),
    IamRouteManifestEntry("GET", "/iam/directory/users", "search_directory"),
    IamRouteManifestEntry("GET", "/iam/directory/roster", "list_directory_roster"),
    IamRouteManifestEntry("GET", "/iam/access-requests", "list_access_requests"),
    IamRouteManifestEntry("POST", "/iam/access-requests", "submit_access_request"),
    IamRouteManifestEntry(
        "POST", "/iam/access-requests/{request_id:str}/decision", "review_access_request"
    ),
    IamRouteManifestEntry("POST", "/iam/access-requests/self", "submit_self_access_request"),
    IamRouteManifestEntry("GET", "/iam/assignments", "list_assignments"),
    IamRouteManifestEntry("GET", "/iam/assignment-cases", "list_cases"),
    IamRouteManifestEntry("POST", "/iam/assignment-cases", "create_case"),
    IamRouteManifestEntry("GET", "/iam/assignment-cases/{case_id:str}", "get_case"),
    IamRouteManifestEntry("POST", "/iam/assignment-cases/{case_id:str}/submit", "submit_case"),
    IamRouteManifestEntry("POST", "/iam/assignment-cases/{case_id:str}/review", "review_case"),
    IamRouteManifestEntry("GET", "/handover/readiness", "readiness"),
    IamRouteManifestEntry("GET", "/handover/goals/invitation", "invitation"),
    IamRouteManifestEntry("GET", "/handover/goals/{goal_id:str}", "get_goal"),
    IamRouteManifestEntry("POST", "/handover/goals/{goal_id:str}/{operation:str}", "command"),
    IamRouteManifestEntry("GET", "/handover/scoped-duties/catalog", "scoped_catalog"),
    IamRouteManifestEntry("GET", "/handover/scoped-duties", "scoped_projection"),
    IamRouteManifestEntry("POST", "/handover/scoped-duty-cases", "create_scoped_case"),
    IamRouteManifestEntry("GET", "/handover/scoped-duty-cases/{case_id:str}", "get_scoped_case"),
    IamRouteManifestEntry(
        "POST", "/handover/scoped-duty-cases/{case_id:str}/submit", "submit_scoped_case"
    ),
    IamRouteManifestEntry(
        "POST", "/handover/scoped-duty-cases/{case_id:str}/review", "review_scoped_case"
    ),
    IamRouteManifestEntry("GET", "/handover/reporting-lines", "current_graph"),
    IamRouteManifestEntry("GET", "/handover/reporting-line-cases", "list_cases"),
    IamRouteManifestEntry("POST", "/handover/reporting-line-cases", "create_case"),
    IamRouteManifestEntry("GET", "/handover/reporting-line-cases/{case_id:str}", "get_case"),
    IamRouteManifestEntry(
        "POST", "/handover/reporting-line-cases/{case_id:str}/confirm", "confirm_case"
    ),
    IamRouteManifestEntry(
        "POST", "/handover/reporting-line-cases/{case_id:str}/review", "review_case"
    ),
    IamRouteManifestEntry("GET", "/models/settings", "get_settings"),
    IamRouteManifestEntry("PUT", "/models/binding-policy", "put_binding_policy"),
    IamRouteManifestEntry("POST", "/models/binding-policy/assess", "post_binding_assessment"),
    IamRouteManifestEntry("POST", "/models/binding-policy/plan", "post_binding_plan"),
    IamRouteManifestEntry("PUT", "/models/web-search-settings", "put_web_search"),
    IamRouteManifestEntry("PUT", "/models/document-ocr-policy", "put_document_ocr_policy"),
    IamRouteManifestEntry("POST", "/models/document-ocr-policy/plan", "post_document_ocr_plan"),
    IamRouteManifestEntry("PUT", "/me/model-preferences", "put_preference"),
    IamRouteManifestEntry("GET", "/runtime/settings", "get_settings"),
    IamRouteManifestEntry("PUT", "/runtime/settings", "put_settings"),
    IamRouteManifestEntry(
        "POST",
        "/runtime/integrations/teams-a1/plan",
        "request_teams_a1_plan",
    ),
    IamRouteManifestEntry(
        "GET",
        "/runtime/integrations/teams-workflow/binding",
        "get_teams_workflow_binding",
    ),
    IamRouteManifestEntry(
        "POST",
        "/runtime/integrations/teams-workflow/test",
        "test_teams_workflow",
    ),
    IamRouteManifestEntry(
        "POST",
        "/runtime/integrations/slack-webhook/test",
        "test_slack_webhook",
    ),
    IamRouteManifestEntry("POST", "/system/kill-switch", "handler"),
    IamRouteManifestEntry("POST", "/system/break-glass/activation", "handler"),
    IamRouteManifestEntry("POST", "/configuration-baselines/review/run", "run_review"),
    IamRouteManifestEntry("POST", "/configuration-baselines/review/resume", "resume_review"),
    IamRouteManifestEntry(
        "POST",
        "/hil/{approval_id}/operator-decision",
        "post_hil_operator_decision",
    ),
    IamRouteManifestEntry("POST", "/hil/slack/interaction", "slack_interaction"),
    IamRouteManifestEntry("GET", "/hil/slack/handoff/{nonce}", "slack_handoff_preview"),
    IamRouteManifestEntry("POST", "/hil/slack/handoff/{nonce}", "slack_handoff_decide"),
    IamRouteManifestEntry(
        "GET",
        "/hil/report-line-contact-requests",
        "list_report_line_contacts",
    ),
    IamRouteManifestEntry(
        "POST",
        "/hil/{approval_id}/report-line-contact",
        "post_report_line_contact",
    ),
    IamRouteManifestEntry("POST", "/hil/{approval_id}/decision", "handler"),
    IamRouteManifestEntry("POST", "/hil/teams-activity", "handler"),
    IamRouteManifestEntry(
        "POST",
        "/runtime/integrations/notifications/delivery-receipt",
        "post_notification_delivery_receipt",
    ),
)


__all__ = ["IAM_FAMILY_MANIFEST", "IamRouteManifestEntry"]
