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
    IamRouteManifestEntry("GET", "/handover/goals/invitation", "invitation"),
    IamRouteManifestEntry("POST", "/handover/goals/{goal_id:str}/{operation:str}", "command"),
    IamRouteManifestEntry("GET", "/models/settings", "get_settings"),
    IamRouteManifestEntry("PUT", "/models/web-search-settings", "put_web_search"),
    IamRouteManifestEntry("PUT", "/me/model-preferences", "put_preference"),
    IamRouteManifestEntry("GET", "/runtime/settings", "get_settings"),
    IamRouteManifestEntry("PUT", "/runtime/settings", "put_settings"),
    IamRouteManifestEntry("POST", "/system/kill-switch", "handler"),
    IamRouteManifestEntry("POST", "/configuration-baselines/review/run", "run_review"),
    IamRouteManifestEntry("POST", "/configuration-baselines/review/resume", "resume_review"),
    IamRouteManifestEntry("POST", "/hil/{approval_id}/decision", "handler"),
)


__all__ = ["IAM_FAMILY_MANIFEST", "IamRouteManifestEntry"]
