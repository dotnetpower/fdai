"""Focused contracts for independently deployed Operator topics."""

from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_MODULE = (_ROOT / "infra/services/operator-service/modules/operator-service/main.tf").read_text(
    encoding="utf-8"
)
_MATRIX = json.loads(
    (_ROOT / "scripts/deployment/service/service-matrix.json").read_text(encoding="utf-8")
)


def test_operator_module_renders_reviewed_request_and_completion_topics() -> None:
    expected = {
        "FDAI_INCIDENT_INTERVENTION_REQUEST_TOPIC": (
            "var.event_topics.incident_intervention_requests"
        ),
        "FDAI_READ_INVESTIGATION_COMPLETION_TOPIC": (
            "var.event_topics.read_investigation_completions"
        ),
        "FDAI_READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP_ID": (
            '"operator-read-investigation-completion-v1"'
        ),
        "FDAI_HIL_DECISION_TOPIC": "var.event_topics.hil_decisions",
        "FDAI_TEAMS_TENANT_ID": "var.hil_callback.teams_tenant_id",
        "FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON": ("var.hil_callback.teams_allowed_service_urls"),
        "FDAI_TEAMS_JWKS_URL": "var.hil_callback.teams_jwks_url",
    }

    for name, value in expected.items():
        assert f'{{ name = "{name}", value = {value} }}' in _MODULE


def test_operator_deploy_contract_requires_reviewed_topic_environment() -> None:
    required = set(_MATRIX["services"]["operator-service"]["required_environment"])

    assert {
        "FDAI_INCIDENT_INTERVENTION_REQUEST_TOPIC",
        "FDAI_READ_INVESTIGATION_COMPLETION_TOPIC",
        "FDAI_READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP_ID",
        "FDAI_HIL_DECISION_TOPIC",
    } <= required


def test_approval_team_channel_is_separate_from_role_groups_and_shared_with_core() -> None:
    core = (
        _ROOT / "infra/services/core-control-plane/modules/core-control-plane/main.tf"
    ).read_text(encoding="utf-8")

    for environment_name in (
        "FDAI_TEAMS_APPROVAL_TEAM_ID",
        "FDAI_TEAMS_APPROVAL_CHANNEL_ID",
    ):
        assert environment_name in _MODULE
        assert environment_name in core
    assert "FDAI_TEAMS_APPROVAL_ACTIVITY_URL" in core
    assert (
        "var.rbac.approvers_group_id"
        not in _MODULE.split(
            "FDAI_TEAMS_APPROVAL_TEAM_ID",
            maxsplit=1,
        )[1].split("FDAI_TEAMS_APPROVAL_CHANNEL_ID", maxsplit=1)[0]
    )
