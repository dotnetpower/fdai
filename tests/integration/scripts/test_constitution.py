from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/quality/architecture/check-constitution.py"
    spec = importlib.util.spec_from_file_location("check_constitution", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_texts(module: ModuleType) -> dict[str, str]:
    ids = "\n".join(module.EXPECTED_IDS)
    trace_rows = "\n".join(f"| {row} | owner | evidence |" for row in module.EXPECTED_TRACE_ROWS)
    autonomy_values = "\n".join(f"`{value}`" for value in module.EXPECTED_AUTONOMY_VALUES)
    safeguards = "\n".join(module.EXPECTED_SAFEGUARDS)
    texts = {
        module.ENGLISH_CONSTITUTION: f"{ids}\n{trace_rows}\n{autonomy_values}\n{safeguards}",
        module.KOREAN_CONSTITUTION: f"{ids}\n{trace_rows}",
    }
    for path, phrases in module.REQUIRED_PHRASES.items():
        texts[path] = "\n".join(filter(None, (texts.get(path), *phrases)))
    return texts


def test_repository_constitution_is_consistent() -> None:
    module = _load_module()

    assert module.validate() == []


def test_agent_contract_separates_delegated_feedback_from_delivery_evidence() -> None:
    instructions = (REPO_ROOT / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    normalized = " ".join(instructions.split())

    assert (
        "Delegated validation of task-owned dirty inputs MAY provide development feedback"
        in normalized
    )
    assert (
        "Evidence attached to a commit, release, or deployment still "
        "requires a clean immutable snapshot" in normalized
    )


def test_agent_contract_requires_local_first_commits() -> None:
    instructions = (REPO_ROOT / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    normalized = " ".join(instructions.split())

    assert "Every agent-authored commit MUST originate in the" in normalized
    assert "create a remote-only commit" in normalized
    assert "create_or_update_file" in normalized
    assert "push_files" in normalized
    assert "MUST NOT substitute for the local commit" in normalized
    assert "only after the local commit exists" in normalized
    assert "verify the remote ref resolves to the expected local commit" in normalized


def test_traceability_manifest_is_complete() -> None:
    module = _load_module()

    assert module._validate_traceability(REPO_ROOT) == []


def test_const_002_implemented_status_requires_fail_closed_proofs() -> None:
    module = _load_module()

    assert module.IMPLEMENTED_PROOF_TESTS["FDAI-CONST-002"] == (
        "packages/service-contracts/tests/test_decision_evidence.py::test_json_schema_requires_authentication_evidence",
        "packages/service-contracts/tests/test_decision_evidence.py::test_synthetic_evidence_never_reaches_live_verification",
        "services/core-control-plane/tests/core/readiness/test_decision_evidence.py::test_missing_evidence_is_denied_because_no_receipt_can_be_verified",
        "tests/integration/scripts/test_decision_boundary_coverage.py::test_the_shipped_inventory_covers_every_registered_boundary",
        "tests/integration/scripts/test_decision_boundary_coverage.py::test_an_intentionally_uncovered_registered_boundary_fails_the_guard",
    )


def test_const_004_implemented_status_requires_versioned_threshold_proofs() -> None:
    module = _load_module()

    assert module.IMPLEMENTED_PROOF_TESTS["FDAI-CONST-004"] == (
        "services/core-control-plane/tests/core/operational_learning/test_threshold_bounds.py::test_every_adaptive_threshold_field_declares_an_ontology_bound",
        "services/core-control-plane/tests/core/operational_learning/test_threshold_bounds.py::test_detection_routing_bounds_load_from_the_pinned_shipped_contract",
        "services/core-control-plane/tests/core/operational_learning/test_threshold_bounds.py::test_every_detection_routing_threshold_stays_inside_its_ontology_bound",
        "services/core-control-plane/tests/core/operational_learning/test_threshold_bounds.py::test_every_production_routing_and_detection_threshold_has_a_versioned_bound",
    )


def test_const_001_implemented_status_requires_runtime_scope_proofs() -> None:
    module = _load_module()

    assert module.IMPLEMENTED_PROOF_TESTS["FDAI-CONST-001"] == (
        "packages/service-contracts/tests/test_runtime_scope.py::test_runtime_scope_receipt_binds_product_and_complete_venue_contract",
        "tests/integration/scripts/test_venue_capability_contract.py::test_a_computed_environment_key_fails_the_ast_gate",
        "tests/integration/scripts/test_venue_capability_contract.py::test_every_service_entrypoint_records_exactly_one_runtime_scope_receipt",
    )


def test_traceability_rejects_missing_evidence_path(tmp_path: Path) -> None:
    module = _load_module()
    manifest = {
        "version": 1,
        "requirements": [
            {
                "id": requirement_id,
                "status": "implemented",
                "owner_docs": ["owner.md"],
                "implementation": ["code.py"],
                "schemas": [],
                "tests": ["test_code.py"],
                "runtime_evidence": ["evidence.log"],
                "gap": None,
            }
            for requirement_id in module.EXPECTED_IDS
        ],
    }
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "constitution-traceability.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    errors = module._validate_traceability(tmp_path)

    assert any("missing path" in error for error in errors)


def test_implemented_status_rejects_unregistered_existing_test(tmp_path: Path) -> None:
    module = _load_module()
    for relative in ("owner.md", "code.py", "test_code.py", "evidence.log"):
        (tmp_path / relative).write_text("placeholder", encoding="utf-8")
    manifest = {
        "version": 1,
        "requirements": [
            {
                "id": requirement_id,
                "status": "implemented" if requirement_id == "FDAI-CONST-003" else "planned",
                "owner_docs": ["owner.md"],
                "implementation": ["code.py"],
                "schemas": [],
                "tests": ["test_code.py"],
                "runtime_evidence": ["evidence.log"],
                "gap": None if requirement_id == "FDAI-CONST-003" else "Not implemented.",
            }
            for requirement_id in module.EXPECTED_IDS
        ],
    }
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "constitution-traceability.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    errors = module._validate_traceability(tmp_path)

    assert any("required proof test is not listed" in error for error in errors)


def test_missing_requirement_id_is_rejected() -> None:
    module = _load_module()
    texts = _valid_texts(module)
    texts[module.ENGLISH_CONSTITUTION] = texts[module.ENGLISH_CONSTITUTION].replace(
        "FDAI-CONST-007", ""
    )

    assert module.validate_texts(texts) == [
        f"{module.ENGLISH_CONSTITUTION}: expected each FDAI-CONST-001..010 once in order"
    ]


def test_missing_traceability_row_is_rejected() -> None:
    module = _load_module()
    texts = _valid_texts(module)
    texts[module.KOREAN_CONSTITUTION] = texts[module.KOREAN_CONSTITUTION].replace(
        "| 007 | owner | evidence |", ""
    )

    assert any(
        "expected traceability rows 001..010 once in order" in error
        for error in module.validate_texts(texts)
    )


def test_missing_mirror_and_obsolete_phrase_are_rejected() -> None:
    module = _load_module()
    texts = _valid_texts(module)
    instruction = ".github/instructions/coding-conventions.instructions.md"
    texts[instruction] = "high-risk never auto-executes"

    errors = module.validate_texts(texts)

    assert any("missing required constitutional phrase" in error for error in errors)
    assert any("obsolete constitutional phrase" in error for error in errors)


def test_missing_core_principle_is_rejected() -> None:
    module = _load_module()
    texts = _valid_texts(module)
    instruction = ".github/copilot-instructions.md"
    texts[instruction] = texts[instruction].replace("Language never grants authority.", "")

    assert any(
        instruction in error and "missing required constitutional phrase" in error
        for error in module.validate_texts(texts)
    )


def test_obsolete_safeguard_count_is_rejected_across_roadmap() -> None:
    module = _load_module()
    texts = _valid_texts(module)
    texts["docs/roadmap/example.md"] = "All four safety invariants apply."

    assert any(
        "obsolete roadmap safeguard phrase" in error for error in module.validate_texts(texts)
    )


def test_autonomy_namespace_and_safeguards_are_structural() -> None:
    module = _load_module()
    texts = _valid_texts(module)
    texts[module.ENGLISH_CONSTITUTION] = (
        texts[module.ENGLISH_CONSTITUTION]
        .replace("`autonomy.a3_e`", "`autonomy.a3`")
        .replace("held logical-target lock with causal ordering", "held lock")
    )

    errors = module.validate_texts(texts)

    assert any("expected exact autonomy machine-value set" in error for error in errors)
    assert any("missing safeguard" in error for error in errors)
