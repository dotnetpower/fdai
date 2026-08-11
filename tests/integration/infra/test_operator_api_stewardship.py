from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def test_operator_api_requires_real_complete_stewardship_bindings() -> None:
    module = (_ROOT / "infra" / "modules" / "operator-api" / "container-app" / "main.tf").read_text(
        encoding="utf-8"
    )

    assert 'trimspace(var.stewardship_maintainers) != ""' in module
    assert 'var.iam_directory_provider == "entra"' in module
    for agent in (
        "Odin",
        "Thor",
        "Forseti",
        "Huginn",
        "Heimdall",
        "Vidar",
        "Var",
        "Bragi",
        "Saga",
        "Mimir",
        "Muninn",
        "Norns",
        "Njord",
        "Freyr",
    ):
        assert f'"{agent}"' in module
    assert "Operator API requires stewardship bindings" in module


def test_inventory_job_inherits_required_runtime_config() -> None:
    job = (
        _ROOT / "infra" / "modules" / "compute" / "container-apps" / "inventory_job.tf"
    ).read_text(encoding="utf-8")

    assert "for_each = local.core_config_env" in job
    assert 'command = ["python", "-m", "fdai.delivery.inventory_sync_cli"]' in job


def test_operator_api_command_identity_can_publish_owned_objects() -> None:
    root = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    module = (_ROOT / "infra/modules/operator-api/container-app/main.tf").read_text(
        encoding="utf-8"
    )

    assert 'name  = "FDAI_COMMAND_MI_CLIENT_ID"' in module
    assert "value = var.command_api_identity_client_id" in module
    assert re.search(
        r'"aw\.pantheon\.objects"\s*=\s*module\.event_bus\.topic_ids\["aw\.pantheon\.objects"\]',
        root,
    )
    assert (
        "(local.semantic_turn_request_topic) = "
        "module.event_bus.topic_ids[local.semantic_turn_request_topic]"
    ) in root
    assert (
        "(local.semantic_turn_projection_topic) = "
        "module.event_bus.topic_ids[local.semantic_turn_projection_topic]"
    ) in root
