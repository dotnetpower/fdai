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
    }

    for name, value in expected.items():
        assert f'{{ name = "{name}", value = {value} }}' in _MODULE


def test_operator_deploy_contract_requires_reviewed_topic_environment() -> None:
    required = set(_MATRIX["services"]["operator-service"]["required_environment"])

    assert {
        "FDAI_INCIDENT_INTERVENTION_REQUEST_TOPIC",
        "FDAI_READ_INVESTIGATION_COMPLETION_TOPIC",
        "FDAI_READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP_ID",
    } <= required
