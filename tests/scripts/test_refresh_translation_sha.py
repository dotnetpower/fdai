"""Tests for scripts/quality/localization/refresh-translation-sha.py.

Covers the historical whole-tree bug (arguments were ignored) and the
idempotency contract (a re-run over an in-sync tree MUST leave every file
byte-identical, including the ``translation_revised`` date).

The module is loaded via ``importlib.util`` because its filename uses a
hyphen, which is not a valid Python identifier.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "quality" / "localization" / "refresh-translation-sha.py"


@pytest.fixture(scope="module")
def script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_translation_sha", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_pair(
    root: Path, name: str, src_body: str, ko_fm_sha: str, ko_body: str
) -> tuple[Path, Path]:
    src = root / f"{name}.md"
    ko = root / f"{name}-ko.md"
    src.write_text(src_body, encoding="utf-8")
    ko.write_text(
        "---\n"
        f"translation_of: {name}.md\n"
        f"translation_source_sha: {ko_fm_sha}\n"
        "translation_revised: 2020-01-01\n"
        "---\n"
        f"{ko_body}",
        encoding="utf-8",
    )
    return src, ko


class TestProcess:
    def test_out_of_sync_is_rewritten_with_new_sha_and_stamp(
        self, script_module: ModuleType, tmp_path: Path
    ) -> None:
        src, ko = _write_pair(tmp_path, "note", "hello world\n", "deadbeef", "body\n")
        expected_sha = script_module.git_hash(src)
        changed, _ = script_module.process(ko, today="2026-07-12")
        assert changed
        after = ko.read_text(encoding="utf-8")
        assert f"translation_source_sha: {expected_sha}" in after
        assert "translation_revised: 2026-07-12" in after

    def test_in_sync_is_idempotent_and_does_not_bump_the_date(
        self, script_module: ModuleType, tmp_path: Path
    ) -> None:
        """Historical bug: any run bumped translation_revised for every file
        (because a fresh 'today' always differed from the stored date), so
        'idempotent' was a lie. Now a matching SHA is a true no-op - the
        file must stay byte-identical and the stale date must NOT move."""
        src = tmp_path / "note.md"
        src.write_text("stable\n", encoding="utf-8")
        current_sha = script_module.git_hash(src)
        _, ko = _write_pair(tmp_path, "note", "stable\n", current_sha, "body\n")
        before = ko.read_text(encoding="utf-8")
        changed, _ = script_module.process(ko, today="2030-12-31")
        after = ko.read_text(encoding="utf-8")
        assert changed is False
        assert before == after
        assert "translation_revised: 2020-01-01" in after

    def test_missing_source_is_skipped(self, script_module: ModuleType, tmp_path: Path) -> None:
        ko = tmp_path / "orphan-ko.md"
        ko.write_text("---\ntranslation_of: orphan.md\n---\nbody\n", encoding="utf-8")
        changed, msg = script_module.process(ko)
        assert changed is False
        assert "no source" in msg

    def test_missing_frontmatter_is_skipped(
        self, script_module: ModuleType, tmp_path: Path
    ) -> None:
        src = tmp_path / "raw.md"
        src.write_text("body\n", encoding="utf-8")
        ko = tmp_path / "raw-ko.md"
        ko.write_text("just body, no front-matter\n", encoding="utf-8")
        changed, msg = script_module.process(ko)
        assert changed is False
        assert "no front-matter" in msg


class TestArgumentScoping:
    def test_explicit_paths_reject_non_ko_arguments(self, script_module: ModuleType) -> None:
        """Historical bug: paths passed on the CLI were silently ignored and
        the script always processed every tracked *-ko.md. Now an argv that
        includes a non-*-ko.md path fails loud (SystemExit) instead of
        silently doing the wrong thing."""
        with pytest.raises(SystemExit) as excinfo:
            script_module._resolve_files(["docs/foo.md"])
        assert "only *-ko.md paths" in str(excinfo.value)

    def test_explicit_paths_return_only_those(self, script_module: ModuleType) -> None:
        result = script_module._resolve_files(["a-ko.md", "b-ko.md"])
        assert result == [Path("a-ko.md"), Path("b-ko.md")]
