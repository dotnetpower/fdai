"""Regression tests for scripts/automation/run-workflow.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "automation" / "run-workflow.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_workflow", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_resume_builds_body_free_exact_process_request() -> None:
    module = _load_script()
    parser = module._parser()
    args = parser.parse_args(["--resume-process-id", "process-123"])

    request = module._request(args, parser)

    assert request.full_url == "http://127.0.0.1:8000/workflows/process-123/resume"
    assert request.method == "POST"
    assert request.data is None
    assert request.headers["Accept"] == "application/json"
    assert "Content-type" not in request.headers


def test_resume_rejects_new_run_inputs() -> None:
    module = _load_script()
    parser = module._parser()
    args = parser.parse_args(
        ["sample-flow", "--target", "resource-1", "--resume-process-id", "process-123"]
    )

    with pytest.raises(SystemExit):
        module._request(args, parser)


def test_new_run_keeps_existing_payload_contract() -> None:
    module = _load_script()
    parser = module._parser()
    args = parser.parse_args(
        [
            "sample-flow",
            "--target",
            "resource-1",
            "--trigger-ts",
            "2026-08-04T00:00:00+00:00",
            "--context",
            "change.reason=approved",
        ]
    )

    request = module._request(args, parser)

    assert request.full_url == "http://127.0.0.1:8000/workflows/run"
    assert json.loads(request.data) == {
        "workflow": "sample-flow",
        "target_resource_id": "resource-1",
        "trigger_ts": "2026-08-04T00:00:00+00:00",
        "context": {"change.reason": "approved"},
    }


def test_new_run_requires_workflow_and_target() -> None:
    module = _load_script()
    parser = module._parser()

    with pytest.raises(SystemExit):
        module._request(parser.parse_args([]), parser)
