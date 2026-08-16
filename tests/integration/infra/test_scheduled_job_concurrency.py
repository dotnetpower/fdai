"""Every scheduled Container Apps Job stays single-process.

The recovery design allows exactly one write-authoritative process per scheduled
tick. Container Apps Jobs have no cross-process reservation, so the deployed
configuration is the constraint: a schedule trigger must pin
`replica_completion_count` and `parallelism` to `1`, and a job must declare
exactly one trigger kind
(``docs/roadmap/deployment/control-plane-disaster-recovery.md``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_MODULE = _ROOT / "infra" / "modules" / "compute" / "container-apps"
_JOB_RESOURCE = re.compile(r'resource\s+"azurerm_container_app_job"\s+"([a-z0-9_]+)"')
# The closing brace is indented by any run of whitespace. Pinning it to exactly
# two spaces would silently match nothing on a reformatted file and turn the
# assertion loop below into a no-op.
_SCHEDULE_BLOCK = re.compile(r"schedule_trigger_config\s*\{(.*?)\n\s*\}", re.S)
_TRIGGERS = ("schedule_trigger_config", "event_trigger_config", "manual_trigger_config")


def _job_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in sorted(_MODULE.glob("*.tf"))
        if _JOB_RESOURCE.search(path.read_text(encoding="utf-8")) is not None
    )


def test_every_job_module_is_discovered() -> None:
    names = {path.name for path in _job_files()}

    assert len(names) >= 10
    assert "scheduler_job.tf" in names


@pytest.mark.parametrize("path", _job_files(), ids=lambda path: path.name)
def test_scheduled_jobs_run_exactly_one_process_per_fire(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    if "schedule_trigger_config" not in source:
        pytest.skip(f"{path.name} declares no schedule trigger")

    blocks = _SCHEDULE_BLOCK.findall(source)

    assert blocks, f"{path.name}: schedule_trigger_config did not parse"
    for block in blocks:
        assert re.search(r"replica_completion_count\s*=\s*1\b", block), path.name
        assert re.search(r"parallelism\s*=\s*1\b", block), path.name


@pytest.mark.parametrize("path", _job_files(), ids=lambda path: path.name)
def test_every_job_declares_exactly_one_trigger_kind(path: Path) -> None:
    source = path.read_text(encoding="utf-8")

    declared = [trigger for trigger in _TRIGGERS if trigger in source]

    assert len(declared) == 1, f"{path.name} declares {declared}"


def test_the_scheduler_tick_is_opt_in_and_single_process() -> None:
    job = (_MODULE / "scheduler_job.tf").read_text(encoding="utf-8")

    assert 'count = var.scheduler_cron_expression == "" ? 0 : 1' in job
    assert "replica_completion_count = 1" in job
    assert "parallelism              = 1" in job


def test_a_relaxed_schedule_block_would_fail_the_gate() -> None:
    relaxed = (
        'resource "azurerm_container_app_job" "example" {\n'
        "  schedule_trigger_config {\n"
        '    cron_expression          = "* * * * *"\n'
        "    replica_completion_count = 2\n"
        "    parallelism              = 2\n"
        "  }\n"
        "}\n"
    )

    blocks = _SCHEDULE_BLOCK.findall(relaxed)

    assert blocks
    assert not re.search(r"replica_completion_count\s*=\s*1\b", blocks[0])
    assert not re.search(r"parallelism\s*=\s*1\b", blocks[0])
