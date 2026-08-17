from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_JOB = _ROOT / "infra/modules/compute/container-apps/analyzer_tick_job.tf"
_MAIN = _ROOT / "infra/main.tf"
_DEPLOY_WORKFLOW = _ROOT / ".github/workflows/deploy-dev.yml"


def test_analyzer_job_uses_inventory_identity_not_executor_identity() -> None:
    source = _JOB.read_text(encoding="utf-8")

    assert "identity_ids = [var.inventory_identity_id]" in source
    assert "identity = var.inventory_identity_id" in source
    assert "identity_ids = [var.executor_identity_id]" not in source
    assert "identity = var.executor_identity_id" not in source


def test_analyzer_job_binds_the_inventory_projection_env_the_cli_reads() -> None:
    """The scheduled tick can only discover targets if the job binds this key."""
    cli = (_ROOT / "services/core-control-plane/src/fdai/delivery/analyzer_tick_cli.py").read_text(
        encoding="utf-8"
    )
    source = _JOB.read_text(encoding="utf-8")

    assert 'INVENTORY_DSN_ENV = "FDAI_INVENTORY_DSN"' in cli
    assert 'name        = "FDAI_INVENTORY_DSN"' in source
    assert 'name  = "FDAI_ANALYZER_TARGETS"' in source


def test_analyzer_job_binds_deployment_supplied_trace_topologies() -> None:
    cli = (_ROOT / "services/core-control-plane/src/fdai/delivery/analyzer_tick_cli.py").read_text(
        encoding="utf-8"
    )
    source = _JOB.read_text(encoding="utf-8")
    root_variables = (_ROOT / "infra/variables.tf").read_text(encoding="utf-8")
    module_variables = (_ROOT / "infra/modules/compute/container-apps/variables.tf").read_text(
        encoding="utf-8"
    )
    main = _MAIN.read_text(encoding="utf-8")
    workflow = _DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert 'TRACE_TOPOLOGIES_ENV = "FDAI_TRACE_TOPOLOGIES_JSON"' in cli
    assert 'name  = "FDAI_TRACE_TOPOLOGIES_JSON"' in source
    assert 'variable "trace_topologies_json"' in root_variables
    assert 'variable "trace_topologies_json"' in module_variables
    assert "trace_topologies_json         = var.trace_topologies_json" in main
    assert "TF_VAR_trace_topologies_json: ${{ vars.TRACE_TOPOLOGIES_JSON }}" in workflow
    assert "-target=module.compute.azurerm_container_app_job.analyzer_tick[0]" in workflow


def test_startup_probe_uses_dedicated_operational_topic_and_identity() -> None:
    source = _MAIN.read_text(encoding="utf-8")

    assert re.search(r'^\s*startup_probe_topic\s*=\s*"runtime\.startup\.probe"$', source, re.M)
    operational_topics = re.search(r"^\s*topics\s*=\s*\[([^]]+)]$", source, re.M)
    assert operational_topics is not None
    assert "local.canary_topic" in operational_topics.group(1)
    assert "local.startup_probe_topic" in operational_topics.group(1)
    assert 'resource "azurerm_role_assignment" "runtime_startup_probe_eventhubs_owner"' in source
    assert "module.event_bus_auxiliary.topic_ids[local.startup_probe_topic]" in source
    assert 'role_definition_name = "Azure Event Hubs Data Owner"' in source
    for name in (
        "startup_kafka_settle_seconds",
        "startup_probe_timeout_seconds",
        "startup_phase_timeout_seconds",
    ):
        assert re.search(rf"^\s*{name}\s*=\s*var\.{name}$", source, re.M)
