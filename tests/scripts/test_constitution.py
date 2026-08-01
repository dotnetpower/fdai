from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    texts = {
        module.ENGLISH_CONSTITUTION: f"{ids}\n{trace_rows}",
        module.KOREAN_CONSTITUTION: f"{ids}\n{trace_rows}",
    }
    for path, phrases in module.REQUIRED_PHRASES.items():
        texts[path] = "\n".join(filter(None, (texts.get(path), *phrases)))
    return texts


def test_repository_constitution_is_consistent() -> None:
    module = _load_module()

    assert module.validate() == []


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


def test_obsolete_safeguard_count_is_rejected_across_roadmap() -> None:
    module = _load_module()
    texts = _valid_texts(module)
    texts["docs/roadmap/example.md"] = "All four safety invariants apply."

    assert any(
        "obsolete roadmap safeguard phrase" in error for error in module.validate_texts(texts)
    )
