from __future__ import annotations

from pathlib import Path

import pytest
from fdai.core.security.code_findings.analysis_build_context import build_analysis_context


def test_context_changes_only_for_language_roots_or_build_configuration(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
    first = build_analysis_context(tmp_path)

    (tmp_path / "src" / "app.py").write_text("value = 2\n", encoding="utf-8")
    source_only = build_analysis_context(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'changed'\n", encoding="utf-8")
    config_changed = build_analysis_context(tmp_path)

    assert first.digest() == source_only.digest()
    assert first.digest() != config_changed.digest()
    assert first.language_roots == {"python": ("src",)}


def test_context_rejects_linked_configuration(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.toml"
    outside.write_text("[project]\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").symlink_to(outside)

    with pytest.raises(ValueError, match="cannot be a symlink"):
        build_analysis_context(tmp_path)
