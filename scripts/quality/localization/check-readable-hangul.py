#!/usr/bin/env python3
"""Reject escaped Hangul prose and optionally rewrite it as readable UTF-8."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from collections.abc import Iterable
from pathlib import Path

SOURCE_SUFFIXES = frozenset(
    {
        ".cjs",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".mjs",
        ".py",
        ".sh",
        ".tf",
        ".ts",
        ".tsx",
        ".yaml",
        ".yml",
    }
)
ESCAPE_RUN = re.compile(r"(?:(?:\\u\{[0-9A-Fa-f]{1,6}\}|\\u[0-9A-Fa-f]{4}|\\U[0-9A-Fa-f]{8}))+")
ESCAPE_TOKEN = re.compile(r"(?:\\u\{([0-9A-Fa-f]{1,6})\}|\\u([0-9A-Fa-f]{4})|\\U([0-9A-Fa-f]{8}))")
ALLOWLIST_PATH = Path("scripts/quality/localization/readable-hangul-allowlist.txt")


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def _is_hangul(codepoint: int) -> bool:
    return (
        0x1100 <= codepoint <= 0x11FF
        or 0x3130 <= codepoint <= 0x318F
        or 0xAC00 <= codepoint <= 0xD7A3
    )


def _codepoint(match: re.Match[str]) -> int:
    value = next(group for group in match.groups() if group is not None)
    return int(value, 16)


def _contains_hangul_escape(value: str) -> bool:
    return any(_is_hangul(_codepoint(match)) for match in ESCAPE_TOKEN.finditer(value))


def _load_allowlist(root: Path) -> tuple[dict[str, tuple[str, ...]], list[str]]:
    path = root / ALLOWLIST_PATH
    if not path.is_file():
        return {}, []
    entries: dict[str, list[str]] = {}
    errors: list[str] = []
    rationale = False
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            rationale = False
            continue
        if line.startswith("#"):
            rationale = True
            continue
        if "\t" not in raw_line:
            errors.append(f"{ALLOWLIST_PATH}:{line_number}: expected <path><TAB><literal>")
            rationale = False
            continue
        relative, literal = raw_line.split("\t", 1)
        if not rationale:
            errors.append(f"{ALLOWLIST_PATH}:{line_number}: entry requires a preceding rationale")
        if not _contains_hangul_escape(literal):
            errors.append(f"{ALLOWLIST_PATH}:{line_number}: literal has no Hangul escape")
        entries.setdefault(relative, []).append(literal)
        rationale = False
    return {key: tuple(values) for key, values in entries.items()}, errors


def _tracked_files(root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return tuple(path for path in result.stdout.decode().split("\0") if path)


def _source_files(root: Path, requested: Iterable[str]) -> tuple[str, ...]:
    candidates = tuple(requested) or _tracked_files(root)
    return tuple(
        sorted(
            {
                Path(path).as_posix()
                for path in candidates
                if Path(path).suffix in SOURCE_SUFFIXES and (root / path).is_file()
            }
        )
    )


def _protected_ranges(text: str, literals: tuple[str, ...]) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    for literal in literals:
        ranges.extend(
            (match.start(), match.end()) for match in re.finditer(re.escape(literal), text)
        )
    return tuple(ranges)


def _overlaps(start: int, end: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(
        start < protected_end and end > protected_start for protected_start, protected_end in ranges
    )


def _rewrite(text: str, literals: tuple[str, ...]) -> tuple[str, int]:
    protected = _protected_ranges(text, literals)
    parts: list[str] = []
    cursor = 0
    replacements = 0
    for match in ESCAPE_RUN.finditer(text):
        if _overlaps(match.start(), match.end(), protected):
            continue
        codepoints = tuple(_codepoint(token) for token in ESCAPE_TOKEN.finditer(match.group(0)))
        if not codepoints or not all(_is_hangul(codepoint) for codepoint in codepoints):
            continue
        decoded = unicodedata.normalize("NFC", "".join(chr(codepoint) for codepoint in codepoints))
        parts.extend((text[cursor : match.start()], decoded))
        cursor = match.end()
        replacements += len(codepoints)
    if replacements == 0:
        return text, 0
    parts.append(text[cursor:])
    return "".join(parts), replacements


def _violations(text: str, literals: tuple[str, ...]) -> list[tuple[int, str]]:
    protected = _protected_ranges(text, literals)
    violations: list[tuple[int, str]] = []
    for match in ESCAPE_TOKEN.finditer(text):
        if not _is_hangul(_codepoint(match)):
            continue
        if _overlaps(match.start(), match.end(), protected):
            continue
        line_number = text.count("\n", 0, match.start()) + 1
        violations.append((line_number, match.group(0)))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="replace non-allowlisted escapes")
    parser.add_argument("paths", nargs="*", help="limit the scan to these repository paths")
    args = parser.parse_args(argv)

    root = _repo_root()
    allowlist, errors = _load_allowlist(root)
    files = _source_files(root, args.paths)
    selected = set(files)
    requested = {Path(path).as_posix() for path in args.paths}
    validate_all = not args.paths or ALLOWLIST_PATH.as_posix() in requested

    for relative, literals in allowlist.items():
        if not validate_all and relative not in selected:
            continue
        path = root / relative
        if not path.is_file():
            errors.append(f"{ALLOWLIST_PATH}: stale path: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        for literal in literals:
            if text.count(literal) != 1:
                errors.append(
                    f"{ALLOWLIST_PATH}: {relative}: allowlisted literal must occur exactly once"
                )

    replacements = 0
    violations: list[str] = []
    for relative in files:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        literals = allowlist.get(relative, ())
        if args.fix:
            rewritten, count = _rewrite(text, literals)
            if count:
                path.write_text(rewritten, encoding="utf-8")
                text = rewritten
                replacements += count
        violations.extend(
            f"{relative}:{line_number}: {token}"
            for line_number, token in _violations(text, literals)
        )

    if errors or violations:
        for error in errors:
            print(f"readable-hangul: ERROR: {error}", file=sys.stderr)
        for violation in violations[:50]:
            print(f"readable-hangul: escaped Hangul literal: {violation}", file=sys.stderr)
        if len(violations) > 50:
            print(
                f"readable-hangul: ... {len(violations) - 50} more occurrence(s)",
                file=sys.stderr,
            )
        print(
            "readable-hangul: FAILED; use literal UTF-8 Korean or run with --fix",
            file=sys.stderr,
        )
        return 1

    action = f", {replacements} token(s) rewritten" if args.fix else ""
    print(f"readable-hangul: OK ({len(files)} file(s) scanned{action})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
