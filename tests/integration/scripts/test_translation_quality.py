"""Tests for the Korean translation quality checker."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _REPO_ROOT / "scripts/quality/localization/check-translation-quality.py"
_SPEC = importlib.util.spec_from_file_location("check_translation_quality", _SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_filename_rule_ignores_localized_image_alt_text() -> None:
    text = "![아키텍처는 catalog.yaml을 로드합니다.](diagram.svg)"

    assert _MODULE.LINK_FILENAME_RE.search(text) is None


def test_filename_rule_still_rejects_translated_link_labels() -> None:
    text = "[구성 catalog.yaml](catalog.yaml)"

    assert _MODULE.LINK_FILENAME_RE.search(text) is not None
