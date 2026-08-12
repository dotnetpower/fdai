#!/usr/bin/env python3
"""Detect translation-quality defects that the SHA parity gate cannot see.

`check-translations.sh` proves a `-ko.md` file is *fresh*. It cannot tell
whether the Korean text is *correct*. Bulk term substitution is fast but
introduces a small set of defects that are invisible to freshness checks and
easy to miss in review, so each one gets a dedicated detector here:

- a canonical English domain term was translated (`shadow` -> a Korean word)
- a product name lost its second word (`Managed Identity` -> `Managed` + Korean)
- markdown indentation collapsed relative to the English source
- an adjective form was spliced onto a verb ending, producing a non-sentence
- a filename inside link display text was translated

Usage:
    check-translation-quality.py [paths...]      # defaults to every -ko.md
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

HANGUL = "가-힣"
ALLOWLIST_PATH = Path("scripts/quality/localization/translation-quality-allowlist.txt")

# Domain vocabulary that must stay English, with the mistranslation seen in
# practice. Keep this list evidence-based: add an entry only after a real
# regression, so the gate stays free of speculative rules.
BANNED_RENDERINGS: tuple[tuple[str, str], ...] = (("shadow", "그림자"),)

# First words of product names. A Hangul word directly after one of these means
# the product name was split mid-phrase. Second words (`Log` in `Activity Log`)
# are deliberately excluded: Korean prose legitimately follows them.
PRODUCT_FIRST_WORDS: tuple[str, ...] = (
    "Managed",
    "Diagnostic",
    "Virtual",
    "Flexible",
    "Cognitive",
)

# Adjective forms produced by term substitution, spliced onto a verb ending.
SPLICE_RE = re.compile(rf"[{HANGUL}]+(?:된|는|한)(?:합니다|하고|하며|하지|했습니다)")

# Legitimate verbs that the broad splice pattern also matches.
SPLICE_ALLOWED = frozenset(
    {
        "제한합니다",
        "제한하고",
        "제한하며",
        "제한하지",
        "제한했습니다",
        "유한하지",
        "무한하지",
    }
)

LINK_FILENAME_RE = re.compile(
    rf"\[[^\]]*[{HANGUL}][^\]]*\.(?:md|py|ts|tsx|js|json|yaml|yml|sh|tf)[^\]]*\]"
)

CODE_FENCE_RE = re.compile(r"^\s*```")
MIN_EN_INDENT_LINES = 5
INDENT_RATIO = 3


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def _load_allowlist(root: Path) -> set[str]:
    path = root / ALLOWLIST_PATH
    if not path.exists():
        return set()
    entries = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            entries.add(line)
    return entries


def _indented_lines(text: str) -> int:
    """Count list-continuation lines, ignoring fenced code."""
    total = 0
    in_fence = False
    for line in text.split("\n"):
        if CODE_FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("  ") and line[2:3].strip():
            total += 1
    return total


def _outside_code(text: str) -> Iterable[tuple[int, str]]:
    """Yield (line number, line) for prose lines only."""
    in_fence = False
    for number, line in enumerate(text.split("\n"), start=1):
        if CODE_FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield number, line


def _check(path: Path, root: Path, allowlist: set[str]) -> list[str]:
    rel = path.relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []

    def report(rule: str, number: int, detail: str) -> None:
        if f"{rel}:{rule}:{detail}" in allowlist:
            return
        problems.append(f"{rel}:{number}: [{rule}] {detail}")

    for number, line in _outside_code(text):
        stripped = re.sub(r"`[^`\n]*`", "", line)

        for english, korean in BANNED_RENDERINGS:
            if korean in stripped:
                report(
                    "domain-term",
                    number,
                    f"'{english}' must stay English, found '{korean}'",
                )

        for word in PRODUCT_FIRST_WORDS:
            match = re.search(rf"\b{word}\s+([{HANGUL}]+)", stripped)
            if match:
                report(
                    "product-name",
                    number,
                    f"'{word} {match.group(1)}' splits a product name",
                )

        for match in SPLICE_RE.finditer(stripped):
            if match.group(0) in SPLICE_ALLOWED:
                continue
            report("grammar-splice", number, f"'{match.group(0)}' reads as a non-sentence")

        for match in LINK_FILENAME_RE.finditer(line):
            report("link-filename", number, f"{match.group(0)} translates a filename")

    english = path.with_name(path.name.replace("-ko.md", ".md"))
    if english.exists():
        en_indent = _indented_lines(english.read_text(encoding="utf-8"))
        ko_indent = _indented_lines(text)
        if en_indent >= MIN_EN_INDENT_LINES and ko_indent * INDENT_RATIO < en_indent:
            report(
                "indentation",
                1,
                f"{ko_indent} indented lines vs {en_indent} in {english.name}",
            )

    return problems


def main(argv: list[str]) -> int:
    root = _repo_root()
    allowlist = _load_allowlist(root)

    if argv:
        paths = [Path(a).resolve() for a in argv]
    else:
        paths = sorted((root / "docs").rglob("*-ko.md")) + [root / "README-ko.md"]

    targets = [p for p in paths if p.name.endswith("-ko.md") and p.exists()]
    problems: list[str] = []
    for path in targets:
        problems.extend(_check(path, root, allowlist))

    if problems:
        for problem in problems:
            print(f"check-translation-quality: {problem}")
        print(
            f"check-translation-quality: FAILED with {len(problems)} finding(s). "
            "See .github/skills/translation-quality/SKILL.md"
        )
        return 1

    print(f"check-translation-quality: OK ({len(targets)} file(s) scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
