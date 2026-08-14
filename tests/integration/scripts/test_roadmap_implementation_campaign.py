from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

AUTOMATION = Path(__file__).resolve().parents[3] / "scripts" / "automation"


def _load() -> ModuleType:
    sys.path.insert(0, str(AUTOMATION))
    path = AUTOMATION / "roadmap_implementation_campaign.py"
    spec = importlib.util.spec_from_file_location("fdai_roadmap_implementation_campaign", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_choose_folder_requires_a_complete_batch() -> None:
    module = _load()
    grouped = {
        "interfaces": [f"docs/roadmap/interfaces/doc-{index}.md" for index in range(10)],
        "operations": [f"docs/roadmap/operations/doc-{index}.md" for index in range(9)],
    }

    selected = module.choose_folder(grouped, chooser=lambda folders: folders[0])

    assert selected == ("interfaces", grouped["interfaces"])
    assert module.choose_folder({"operations": grouped["operations"]}) is None


def test_campaign_prompt_requires_exact_batch_and_hardening_floor() -> None:
    module = _load()
    candidates = [f"docs/roadmap/interfaces/doc-{index}.md" for index in range(12)]

    prompt = module.campaign_prompt("interfaces", candidates, issue=123)

    assert "exactly 10 canonical English documents" in prompt
    assert "at least 10 explicit" in prompt
    assert "remaining verified severity is Low or none" in prompt
    assert "issue #123" in prompt
    assert "Never run repository-wide validation" in prompt


def test_validate_completed_result_enforces_batch_rounds_and_severity(tmp_path: Path) -> None:
    module = _load()
    candidates = []
    evidence = tmp_path / "tests/test_example.py"
    evidence.parent.mkdir()
    evidence.write_text("def test_example(): pass\n", encoding="utf-8")
    for index in range(10):
        relative = f"docs/roadmap/interfaces/doc-{index}.md"
        candidates.append(relative)
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Example\n", encoding="utf-8")
    payload = {
        "outcome": "completed",
        "folder": "interfaces",
        "documents": candidates,
        "hardening_rounds": 10,
        "remaining_max_severity": "low",
        "summary": "Implemented and hardened ten bounded items.",
        "evidence_paths": ["tests/test_example.py"],
        "tests": ["pytest tests/test_example.py: passed"],
    }

    result = module.validate_result(
        payload,
        repo_root=tmp_path,
        folder="interfaces",
        candidates=candidates,
    )

    assert result["documents"] == candidates
    with pytest.raises(RuntimeError, match="at least ten hardening rounds"):
        module.validate_result(
            {**payload, "hardening_rounds": 9},
            repo_root=tmp_path,
            folder="interfaces",
            candidates=candidates,
        )
    with pytest.raises(RuntimeError, match="above Low"):
        module.validate_result(
            {**payload, "remaining_max_severity": "medium"},
            repo_root=tmp_path,
            folder="interfaces",
            candidates=candidates,
        )


def test_require_document_updates_checks_both_languages() -> None:
    module = _load()
    documents = [f"docs/roadmap/interfaces/doc-{index}.md" for index in range(10)]
    changed = [
        path
        for document in documents
        for path in (document, document.removesuffix(".md") + "-ko.md")
    ]

    module._require_document_updates({"documents": documents}, changed)
    with pytest.raises(RuntimeError, match="English/Korean"):
        module._require_document_updates({"documents": documents}, changed[:-1])


def test_installer_requires_explicit_issue_and_repeats_persistently(tmp_path: Path) -> None:
    path = AUTOMATION / "install_roadmap_implementation_campaign.py"
    spec = importlib.util.spec_from_file_location("fdai_roadmap_campaign_installer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    installer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = installer
    spec.loader.exec_module(installer)

    service, timer = installer._unit_text(tmp_path.resolve(), issue=123)

    assert "roadmap_implementation_campaign.py" in service
    assert "--issue 123" in service
    assert "--max-active-sessions 1" in service
    assert "OnUnitInactiveSec=5min" in timer
    assert "Persistent=true" in timer
    assert "TimeoutStartSec=5h" in service
