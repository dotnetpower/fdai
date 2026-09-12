"""Keep local validation examples bounded and subordinate to the Testing contract."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GUIDANCE_PATHS = (
    ".github/skills/coding-hardening/SKILL.md",
    ".github/skills/i18n-catalog/SKILL.md",
    ".github/skills/translation-quality/SKILL.md",
    ".github/skills/documentation-writing/SKILL.md",
    ".github/skills/roadmap-implementation-tracking/SKILL.md",
    ".github/skills/manual-studio/SKILL.md",
    ".github/skills/console-ui-ux/SKILL.md",
    ".github/prompts/verify.prompt.md",
    ".github/prompts/harden-coverage.prompt.md",
    ".github/prompts/critique-batch.prompt.md",
    ".github/instructions/documentation-style.instructions.md",
)


@pytest.mark.parametrize("relative_path", GUIDANCE_PATHS)
def test_guidance_links_authoritative_testing_contract(relative_path: str) -> None:
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    assert "coding-conventions.instructions.md#testing" in text


@pytest.mark.parametrize("relative_path", GUIDANCE_PATHS)
def test_translation_refresh_examples_require_reviewed_korean_paths(relative_path: str) -> None:
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    commands = re.findall(r"python3 [^\n`]*refresh-translation-sha\.py([^\n`]*)", text)

    for arguments in commands:
        paths = arguments.strip().split()
        assert paths, f"{relative_path}: no-path refresh can stamp unrelated translations current"
        assert all(path.strip("<>").endswith("-ko.md") for path in paths)
        assert "review" in text.lower(), f"{relative_path}: refresh needs semantic review"


@pytest.mark.parametrize("relative_path", GUIDANCE_PATHS)
def test_scopable_local_checker_examples_name_paths(relative_path: str) -> None:
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    commands = re.findall(
        r"(?:bash|python3) scripts/quality/(?:repository|localization)/"
        r"(?:check-punctuation\.sh|check-readable-hangul\.py|"
        r"check-translations\.sh|check-translation-quality\.py)"
        r"([^\n`]*)",
        text,
    )

    assert all(arguments.strip() for arguments in commands), relative_path


def test_verify_prompt_runs_supplied_pytest_selectors_directly() -> None:
    text = (REPO_ROOT / ".github/prompts/verify.prompt.md").read_text(encoding="utf-8")

    assert "uv run pytest -q --no-cov <supplied-test-paths-or-node-ids>" in text
    assert "verify.sh --full" not in text
    assert "only for an explicit local whole-suite request" in text
    assert "merge or release request alone does not trigger it" in " ".join(text.split())


@pytest.mark.parametrize(
    "relative_path",
    (
        ".github/skills/coding-hardening/SKILL.md",
        ".github/prompts/harden-coverage.prompt.md",
    ),
)
def test_hardening_uses_focused_coverage_and_existing_hints(relative_path: str) -> None:
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    assert "--cov=src/fdai" not in text
    assert '-o addopts=""' not in text
    assert "after each edit" not in text
    assert "candidate list" in text
    assert "explicit local whole-suite request" in text


def test_single_module_coverage_keeps_the_configured_floor() -> None:
    text = (REPO_ROOT / ".github/skills/coding-hardening/SKILL.md").read_text(encoding="utf-8")

    assert "--cov=fdai.<dotted.module>" in text
    assert "--cov-fail-under=90" in text
    assert "[tool.coverage.report]" in text


def test_visual_guidance_declares_incremental_and_deliverable_scopes() -> None:
    manual = (REPO_ROOT / ".github/skills/manual-studio/SKILL.md").read_text(encoding="utf-8")
    console = (REPO_ROOT / ".github/skills/console-ui-ux/SKILL.md").read_text(encoding="utf-8")

    assert "| Isolated slide copy or diagram |" in manual
    assert "Every slide in each affected book" in manual
    assert "| Full deliverable release |" in manual
    assert "exported PDFs" in manual
    assert "Isolated nonvisual" in console
    assert "A full visual deliverable" in " ".join(console.split())
    assert "Skipped or unexercised steps never count as `passed`" in console
