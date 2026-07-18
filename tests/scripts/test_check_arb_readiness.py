"""Architecture-review readiness contract validation."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import yaml

_REPO_ROOT = Path(__file__).parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "governance" / "check-arb-readiness.py"
_MANIFEST = _REPO_ROOT / "config" / "architecture-review.yaml"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_check_arb_readiness", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MOD = _load_script()


def _manifest() -> dict[str, object]:
    raw = yaml.safe_load(_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def test_upstream_manifest_is_structurally_valid() -> None:
    _MOD.validate_contract(_manifest(), _REPO_ROOT, require_production_ready=False)


def test_production_mode_rejects_open_blockers() -> None:
    with pytest.raises(ValueError, match="unresolved critical/high blockers"):
        _MOD.validate_contract(_manifest(), _REPO_ROOT, require_production_ready=True)


def test_duplicate_artifact_id_is_rejected() -> None:
    raw = copy.deepcopy(_manifest())
    review = raw["architecture_review"]
    assert isinstance(review, dict)
    artifacts = review["artifacts"]
    assert isinstance(artifacts, list)
    artifacts.append(copy.deepcopy(artifacts[0]))

    with pytest.raises(ValueError, match="duplicate artifact id"):
        _MOD.validate_contract(raw, _REPO_ROOT, require_production_ready=False)


def test_missing_evidence_path_is_rejected() -> None:
    raw = copy.deepcopy(_manifest())
    review = raw["architecture_review"]
    assert isinstance(review, dict)
    artifacts = review["artifacts"]
    assert isinstance(artifacts, list)
    artifact = artifacts[0]
    assert isinstance(artifact, dict)
    artifact["evidence"] = ["docs/does-not-exist.md"]

    with pytest.raises(ValueError, match="references missing evidence"):
        _MOD.validate_contract(raw, _REPO_ROOT, require_production_ready=False)


def test_complete_production_bindings_pass_strict_mode() -> None:
    raw = copy.deepcopy(_manifest())
    review = raw["architecture_review"]
    assert isinstance(review, dict)
    review["design_review_status"] = "approved"
    review["production_approval_status"] = "ready"
    artifacts = review["artifacts"]
    assert isinstance(artifacts, list)
    for artifact in artifacts:
        assert isinstance(artifact, dict)
        artifact["status"] = "ready"
    blockers = review["blockers"]
    assert isinstance(blockers, list)
    for blocker in blockers:
        assert isinstance(blocker, dict)
        blocker["status"] = "resolved"
    gate = review["production_gate"]
    assert isinstance(gate, dict)
    required_owners = gate["required_owner_slots"]
    required_evidence = gate["required_evidence"]
    assert isinstance(required_owners, list)
    assert isinstance(required_evidence, list)
    gate["owner_bindings"] = {
        slot: {"subject": f"group:{slot}", "escalation": "platform-maintainers"}
        for slot in required_owners
    }
    gate["evidence_bindings"] = {
        item: {
            "uri": f"evidence://{item}",
            "sha256": "a" * 64,
            "approved_by": "group:architecture-reviewers",
            "approved_at": "2026-07-13T00:00:00Z",
        }
        for item in required_evidence
    }

    _MOD.validate_contract(raw, _REPO_ROOT, require_production_ready=True)
