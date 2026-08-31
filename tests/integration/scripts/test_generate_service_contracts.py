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
    assert "class OperatorCoreRequestV1_5_0(TypedDict):" in next(
        content for path, content in rendered.items() if path.endswith("contracts.py")
    )
    assert "export interface CoreOperatorProjectionV1_4_0" in next(
        content for path, content in rendered.items() if path.endswith(".ts")
    )


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
