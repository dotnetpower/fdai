"""Every scheduled Container Apps Job stays single-process.

The recovery design allows exactly one write-authoritative process per scheduled
tick. Container Apps Jobs have no cross-process reservation, so the deployed
configuration is the constraint: `replica_completion_count` and `parallelism`
must both be `1`, and the schedule trigger must be the only trigger
(``docs/roadmap/deployment/control-plane-disaster-recovery.md``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_MODULE = _ROOT / "infra" / "modules" / "compute" / "container-apps"
_JOB_RESOURCE = re.compile(r'resource\s+"azurerm_container_app_job"\s+"([a-z0-9_]+)"')
_SCHEDULE_BLOCK = re.compile(
    r"schedule_trigger_config\s*\{(.*?)\n  \}",
    re.S,
)


def _job_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in sorted(_MODULE.glob("*.tf"))
        if _JOB_RESOURCE.search(path.read_text(encoding="utf-8")) is not None
    )


def test_every_job_module_is_discovered() -> None:
    assert len(_job_files()) >= 10


@pytest.mark.parametrize("path", _job_files(), ids=lambda path: path.name)
def test_scheduled_jobs_run_exactly_one_process_per_fire(path: Path) -> None:
    source = path.read_text(encoding="utf-8")

    for block in _SCHEDULE_BLOCK.findall(source):
        assert re.search(r"replica_completion_count\s*=\s*1\b", block), path.name
        assert re.search(r"parallelism\s*=\s*1\b", block), path.name


@pytest.mark.parametrize("path", _job_files(), ids=lambda path: path.name)
def test_scheduled_jobs_declare_no_second_trigger(path: Path) -> None:
    source = path.read_text(encoding="utf-8")

    if "schedule_trigger_config" not in source:
        return
    assert "event_trigger_config" not in source, path.name
    assert "manual_trigger_config" not in source, path.name


def test_the_scheduler_tick_is_opt_in_and_single_process() -> None:
    job = (_MODULE / "scheduler_job.tf").read_text(encoding="utf-8")

    assert 'count = var.scheduler_cron_expression == "" ? 0 : 1' in job
    assert "replica_completion_count = 1" in job
    assert "parallelism              = 1" in job
