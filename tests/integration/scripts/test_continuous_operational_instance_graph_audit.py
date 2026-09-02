from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER = (
    REPO_ROOT / "scripts/quality/architecture/check-continuous-operational-instance-graph-audit.py"
)
AUDIT = REPO_ROOT / "config/continuous-operational-instance-graph-audit.json"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_continuous_operational_instance_graph_audit",
        CHECKER,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload() -> dict[str, object]:
    value = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_repository_audit_is_complete_and_references_existing_evidence() -> None:
    module = _load_module()

    assert module.validate() == []


def test_audit_rejects_a_missing_required_stage(tmp_path: Path) -> None:
    module = _load_module()
    payload = _payload()
    stages = payload["stages"]
    assert isinstance(stages, list)
    payload["stages"] = stages[:-1]
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps(payload), encoding="utf-8")

    errors = module.validate(audit_path=audit)

    assert any("stage ids must equal" in error for error in errors)
    assert any("stage families must equal" in error for error in errors)


def test_audit_rejects_an_open_stage_without_the_exact_gap(tmp_path: Path) -> None:
    module = _load_module()
    payload = _payload()
    stages = payload["stages"]
    assert isinstance(stages, list)
    graph_first = next(stage for stage in stages if stage["id"] == "graph-first-query")
    graph_first_index = stages.index(graph_first)
    graph_first["state"] = "in-progress"
    graph_first["missing_binding"] = None
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps(payload), encoding="utf-8")

    errors = module.validate(audit_path=audit)

    assert errors == [f"stages[{graph_first_index}] open work must name its exact missing binding"]
