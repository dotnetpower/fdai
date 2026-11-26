"""Pin bilingual roadmap documents to the same section and table structure.

`check-translations.sh` compares source digests, so a heading or table header removed from one
language passes every existing gate while the pair silently diverges.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_DOCS = _ROOT / "docs"
_HEADING = re.compile(r"^#{2,6}\s+\S", re.MULTILINE)
_TABLE_DELIMITER = re.compile(r"^\|(?:\s*:?-{2,}:?\s*\|)+\s*$", re.MULTILINE)


def _translated_pairs() -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for translation in sorted(_DOCS.rglob("*-ko.md")):
        english = translation.with_name(f"{translation.name.removesuffix('-ko.md')}.md")
        if english.is_file():
            pairs.append((english, translation))
    return pairs


def _structure(path: Path) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    return len(_HEADING.findall(text)), len(_TABLE_DELIMITER.findall(text))


def test_translated_documents_keep_the_same_section_and_table_structure() -> None:
    pairs = _translated_pairs()
    assert pairs, "no translated roadmap document pairs were discovered"

    divergent = [
        (
            english.relative_to(_ROOT).as_posix(),
            _structure(english),
            _structure(translation),
        )
        for english, translation in pairs
        if _structure(english) != _structure(translation)
    ]

    assert divergent == [], (
        f"translated documents diverge in (heading count, table count): {divergent}"
    )


def test_every_table_header_has_a_delimiter_row() -> None:
    orphaned: list[str] = []
    for english, translation in _translated_pairs():
        for path in (english, translation):
            lines = path.read_text(encoding="utf-8").splitlines()
            fenced = False
            for index, line in enumerate(lines):
                if line.lstrip().startswith("```"):
                    fenced = not fenced
                    continue
                if fenced or not line.startswith("|"):
                    continue
                previous = lines[index - 1] if index else ""
                if previous.startswith("|"):
                    continue
                following = lines[index + 1] if index + 1 < len(lines) else ""
                if not _TABLE_DELIMITER.fullmatch(following):
                    orphaned.append(f"{path.relative_to(_ROOT).as_posix()}:{index + 1}")

    assert orphaned == [], f"table rows without a header delimiter: {orphaned}"
