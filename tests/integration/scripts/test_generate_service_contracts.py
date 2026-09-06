"""Regression tests for deterministic service-contract generation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATOR_PATH = REPO_ROOT / "scripts" / "quality" / "contracts" / "generate_service_contracts.py"
POLICY_PATH = REPO_ROOT / "packages" / "service-contracts" / "contract-generation.json"


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_service_contracts", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generation_policy_and_committed_artifacts_are_current() -> None:
    generator = _generator()
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    generator.validate_policy(policy, REPO_ROOT)
    rendered = generator.render_artifacts(policy, REPO_ROOT)

    assert set(rendered) == {
        "console/src/generated/service-contracts.ts",
        "packages/service-contracts/src/fdai_service_contracts/generated/__init__.py",
        "packages/service-contracts/src/fdai_service_contracts/generated/contracts.py",
    }
    assert generator.check_artifacts(rendered, REPO_ROOT) == []
    assert "class OperatorCoreRequestV1_6_0(TypedDict):" in next(
        content for path, content in rendered.items() if path.endswith("contracts.py")
    )
    assert "export interface CoreOperatorProjectionV1_6_0" in next(
        content for path, content in rendered.items() if path.endswith(".ts")
    )
    python = next(content for path, content in rendered.items() if path.endswith("contracts.py"))
    typescript = next(content for path, content in rendered.items() if path.endswith(".ts"))
    for name in ("CoreOperatorProjectionV1_4_0", "OperatorCoreRequestV1_5_0"):
        assert f"class {name}(TypedDict):" in python
        assert f"export interface {name}" in typescript
    assert "CoreOperatorProjectionV1_5_0" not in python


def test_check_rejects_a_hand_edited_artifact(tmp_path: Path) -> None:
    generator = _generator()
    relative = "generated/contracts.py"
    rendered = {relative: "expected\n"}
    artifact = tmp_path / relative
    artifact.parent.mkdir(parents=True)
    artifact.write_text("hand edited\n", encoding="utf-8")

    assert generator.check_artifacts(rendered, tmp_path) == [
        "generated artifact is stale or hand-edited: generated/contracts.py"
    ]


def test_advisory_projection_schema_matches_its_owned_generator() -> None:
    path = REPO_ROOT / "scripts/quality/contracts/generate_adaptive_answer_schema.py"
    spec = importlib.util.spec_from_file_location("generate_adaptive_answer_schema", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    artifact = (
        REPO_ROOT
        / "packages/service-contracts/src/fdai_service_contracts/schemas"
        / "core-operator-projection/1.6.0.json"
    )
    assert artifact.read_text(encoding="utf-8") == module.render_schema()
    request_artifact = artifact.parents[1] / "operator-core-request/1.6.0.json"
    assert request_artifact.read_text(encoding="utf-8") == module.render_request_schema()
