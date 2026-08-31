"""Complete-inventory coverage guard for decision-critical evidence admission."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "quality" / "architecture" / "check-decision-boundary-coverage.py"
INVENTORY = REPO_ROOT / "config" / "decision-boundary-inventory.json"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_decision_boundary_coverage", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checker() -> ModuleType:
    return _load_module()


@pytest.fixture
def inventory() -> dict[str, Any]:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def _write(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def test_the_shipped_inventory_covers_every_registered_boundary(checker: ModuleType) -> None:
    assert checker.validate(root=REPO_ROOT, inventory_path=INVENTORY) == []
    assert checker.main(["--root", str(REPO_ROOT), "--inventory", str(INVENTORY)]) == 0


def test_the_inventory_registers_every_boundary_and_purpose_in_the_source_tree(
    inventory: dict[str, Any],
) -> None:
    registered = {boundary["id"] for boundary in inventory["boundaries"]}
    assert len(registered) == len(inventory["boundaries"])
    assert {"causal-closure", "effect-model-activation", "workflow-gate", "workflow-outcome"} <= (
        registered
    )
    for boundary in inventory["boundaries"]:
        assert (REPO_ROOT / boundary["module"]).is_file()
        assert boundary["tests"]


def test_an_intentionally_uncovered_registered_boundary_fails_the_guard(
    checker: ModuleType,
    inventory: dict[str, Any],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A registered boundary that decides positively without resolving the shared
    # admission contract is exactly the failure this guard exists to catch.
    root = tmp_path / "repo"
    module_relative = "src/uncovered_boundary.py"
    module_path = root / module_relative
    module_path.parent.mkdir(parents=True)
    module_path.write_text(
        "UNCOVERED_EVIDENCE_PURPOSE = 'uncovered'\n\n\ndef approve() -> bool:\n    return True\n",
        encoding="utf-8",
    )
    shared_relative = "src/decision_evidence_verifier.py"
    (root / shared_relative).write_text(
        "class DecisionEvidenceAdmission: ...\n"
        "class DecisionEvidenceAdmissionProvider: ...\n"
        "def assess_decision_evidence_admission(): ...\n",
        encoding="utf-8",
    )
    test_relative = "tests/test_uncovered_boundary.py"
    (root / "tests").mkdir()
    (root / test_relative).write_text("def test_uncovered() -> None: ...\n", encoding="utf-8")
    matrix_relative = "tests/test_matrix.py"
    (root / matrix_relative).write_text(
        "\n".join(f"# {name}" for name in checker.REQUIRED_NEGATIVE_CLASSES) + "\n",
        encoding="utf-8",
    )
    document = {
        "version": inventory["version"],
        "description": inventory["description"],
        "shared_admission": {
            **inventory["shared_admission"],
            "source": shared_relative,
        },
        "source_roots": ["src"],
        "boundaries": [
            {
                "id": "uncovered-boundary",
                "positive_decision": "Approve without decision-critical evidence.",
                "module": module_relative,
                "purpose_constant": "UNCOVERED_EVIDENCE_PURPOSE",
                "purpose_id": "uncovered",
                "tests": [test_relative],
            }
        ],
        "negative_evidence_matrix": {
            "gate": shared_relative,
            "tests": [matrix_relative],
            "classes": list(checker.REQUIRED_NEGATIVE_CLASSES),
        },
    }
    inventory_path = _write(tmp_path / "inventory.json", document)

    errors = checker.validate(root=root, inventory_path=inventory_path)

    assert any("uncovered-boundary" in error and "does not import" in error for error in errors)
    assert any("uncovered-boundary" in error and "does not call" in error for error in errors)
    assert any("uncovered-boundary" in error and "fail closed" in error for error in errors)
    assert checker.main(["--root", str(root), "--inventory", str(inventory_path)]) == 1
    assert "uncovered-boundary" in capsys.readouterr().err


def test_an_unregistered_source_boundary_fails_the_guard(
    checker: ModuleType,
    inventory: dict[str, Any],
    tmp_path: Path,
) -> None:
    # Completeness is bidirectional: a module that resolves the shared admission but
    # is absent from the inventory must fail rather than silently pass.
    document = copy.deepcopy(inventory)
    document["boundaries"] = [
        boundary for boundary in document["boundaries"] if boundary["id"] != "workflow-outcome"
    ]
    inventory_path = _write(tmp_path / "inventory.json", document)

    errors = checker.validate(root=REPO_ROOT, inventory_path=inventory_path)

    assert any(
        "core/workflow/outcome_verification.py" in error and "not a registered boundary" in error
        for error in errors
    )


def test_an_undeclared_evidence_purpose_fails_the_guard(
    checker: ModuleType,
    inventory: dict[str, Any],
    tmp_path: Path,
) -> None:
    document = copy.deepcopy(inventory)
    document["purpose_declarations"] = []
    inventory_path = _write(tmp_path / "inventory.json", document)

    errors = checker.validate(root=REPO_ROOT, inventory_path=inventory_path)

    assert any("INCIDENT_EVIDENCE_PURPOSE" in error for error in errors)


def test_a_drifted_purpose_identifier_fails_the_guard(
    checker: ModuleType,
    inventory: dict[str, Any],
    tmp_path: Path,
) -> None:
    document = copy.deepcopy(inventory)
    for boundary in document["boundaries"]:
        if boundary["id"] == "causal-closure":
            boundary["purpose_id"] = "causal-closure-v2"
    inventory_path = _write(tmp_path / "inventory.json", document)

    errors = checker.validate(root=REPO_ROOT, inventory_path=inventory_path)

    assert any("CAUSAL_CLOSURE_EVIDENCE_PURPOSE" in error for error in errors)


def test_an_incomplete_negative_evidence_matrix_fails_the_guard(
    checker: ModuleType,
    inventory: dict[str, Any],
    tmp_path: Path,
) -> None:
    document = copy.deepcopy(inventory)
    document["negative_evidence_matrix"]["classes"] = ["missing", "stale"]
    inventory_path = _write(tmp_path / "inventory.json", document)

    errors = checker.validate(root=REPO_ROOT, inventory_path=inventory_path)

    assert any("negative_evidence_matrix.classes" in error for error in errors)


def test_an_unsorted_or_duplicated_inventory_fails_the_guard(
    checker: ModuleType,
    inventory: dict[str, Any],
    tmp_path: Path,
) -> None:
    document = copy.deepcopy(inventory)
    document["boundaries"] = list(reversed(document["boundaries"]))
    inventory_path = _write(tmp_path / "inventory.json", document)

    errors = checker.validate(root=REPO_ROOT, inventory_path=inventory_path)

    assert any("sorted by 'id'" in error for error in errors)
