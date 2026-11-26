"""Diff guard for remediation changes (standard library only).

The guard inspects a unified diff produced while a coding agent remediates a fix group. It runs in
two places with the same code: on the developer's machine through the remediation-pack helper,
and on the FDAI server when a result is imported. It rejects:

- edits outside the fix group's allowed paths, and edits to forbidden paths (scanner ignore files,
  the pack itself);
- added lines that suppress a scanner, skip a test, disable TLS verification, or swallow errors;
- deleted test files and net removal of assertions in test files;
- binary changes and diffs above the size limit, which the guard cannot inspect.

This module is copied verbatim into every remediation pack as ``tools/fdai_diff_guard.py``, so it
must import only the Python standard library.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_HEADER = re.compile(r'^diff --git ("(?:[^"\\]|\\.)*"|\S+) ("(?:[^"\\]|\\.)*"|\S+)$')
_MAX_LINE = 10_000
UNPARSEABLE = "\x00unparseable"


@dataclass
class FileDiff:
    old_path: str | None = None
    new_path: str | None = None
    binary: bool = False
    added: list[tuple[int, str]] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""

    @property
    def deleted(self) -> bool:
        return self.new_path is None and self.old_path is not None


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a path glob where ``**/`` spans directories and ``*`` stays in one segment."""
    while "**/**/" in pattern:  # repeated spans add nothing but backtracking cost
        pattern = pattern.replace("**/**/", "**/")
    out: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return re.compile("^" + "".join(out) + "$")


def path_matches(path: str, globs: Sequence[str]) -> bool:
    return any(glob_to_regex(glob).match(path) for glob in globs)


def _unquote(value: str) -> str:
    """Decode git's C-style quoted path, or return a marker that fails every path check."""
    if not (len(value) >= 2 and value.startswith('"') and value.endswith('"')):
        return value
    try:
        raw = value[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
        return raw.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return UNPARSEABLE


def _strip_prefix(value: str) -> str | None:
    value = _unquote(value.strip())
    if value == "/dev/null":
        return None
    return value[2:] if value[:2] in ("a/", "b/") else value


def parse_unified_diff(text: str) -> list[FileDiff]:
    """Parse ``git diff`` output into per-file added and removed lines."""
    files: list[FileDiff] = []
    current: FileDiff | None = None
    old_left = new_left = 0
    new_line = 0
    for line in text.splitlines():
        if old_left > 0 or new_left > 0:
            if line.startswith("\\"):
                continue
            tag, body = line[:1], line[1:][:_MAX_LINE]
            if current is not None and tag == "+":
                current.added.append((new_line, body))
                new_line += 1
                new_left -= 1
            elif current is not None and tag == "-":
                current.removed.append(body)
                old_left -= 1
            else:
                new_line += 1
                old_left -= 1
                new_left -= 1
            continue
        if line.startswith("diff --git "):
            current = FileDiff()
            files.append(current)
            header = _HEADER.match(line)
            if header is not None and '"' in line:
                current.old_path = _strip_prefix(header.group(1))
                current.new_path = _strip_prefix(header.group(2))
            else:
                parts = line[len("diff --git ") :].split(" b/", 1)
                current.old_path = _strip_prefix(parts[0])
                current.new_path = _strip_prefix("b/" + parts[1]) if len(parts) == 2 else None
        elif current is None:
            continue
        elif line.startswith("--- "):
            current.old_path = _strip_prefix(line[4:])
        elif line.startswith("+++ "):
            current.new_path = _strip_prefix(line[4:])
        elif line.startswith("deleted file mode"):
            current.new_path = None
        elif line.startswith("new file mode"):
            current.old_path = None
        elif line.startswith("rename from "):
            current.old_path = _unquote(line[len("rename from ") :])
        elif line.startswith("rename to "):
            current.new_path = _unquote(line[len("rename to ") :])
        elif line.startswith("Binary files") or line.startswith("GIT binary patch"):
            current.binary = True
        elif (match := _HUNK.match(line)) is not None:
            old_left = int(match.group(1)) if match.group(1) is not None else 1
            new_line = int(match.group(2))
            new_left = int(match.group(3)) if match.group(3) is not None else 1
    return files


def _violation(rule_id: str, path: str, line: int | None, detail: str) -> dict[str, object]:
    return {"rule_id": rule_id, "path": path, "line": line, "detail": detail}


def evaluate_diff(
    diff_text: str, allowed_paths: Sequence[str], policy: Mapping[str, object]
) -> dict[str, object]:
    """Return ``{"ok": bool, "violations": [...], "files_checked": int}`` for ``diff_text``.

    ``policy`` is the remediation policy document (``remediation-policy.json`` in a pack).
    """
    limits = policy.get("limits")
    max_bytes = (
        int(limits.get("max_diff_bytes", 5_000_000)) if isinstance(limits, Mapping) else 5_000_000
    )
    if len(diff_text.encode("utf-8")) > max_bytes:
        return {
            "ok": False,
            "violations": [
                _violation("diff-too-large", "", None, f"diff exceeds {max_bytes} bytes")
            ],
            "files_checked": 0,
        }
    test_globs = [str(glob) for glob in _seq(policy.get("test_path_globs"))]
    forbidden_paths = [
        entry for entry in _seq(policy.get("forbidden_paths")) if isinstance(entry, Mapping)
    ]
    patterns = [
        (str(entry["id"]), re.compile(str(entry["pattern"])), str(entry.get("description", "")))
        for entry in _seq(policy.get("forbidden_added_patterns"))
        if isinstance(entry, Mapping)
    ]
    assertions = [
        re.compile(str(pattern)) for pattern in _seq(policy.get("test_assertion_patterns"))
    ]
    violations: list[dict[str, object]] = []
    files = parse_unified_diff(diff_text)
    for diff in files:
        path = diff.path
        touched = [p for p in dict.fromkeys((diff.old_path, diff.new_path)) if p]
        if any(p == UNPARSEABLE or "\x00" in p for p in touched):
            violations.append(_violation("unsafe-path", path, None, "path could not be decoded"))
        for candidate in touched:
            for entry in forbidden_paths:
                globs = [str(glob) for glob in _seq(entry.get("globs"))]
                if path_matches(candidate, globs):
                    violations.append(
                        _violation(
                            str(entry["id"]), candidate, None, str(entry.get("description", ""))
                        )
                    )
            if not path_matches(candidate, allowed_paths):
                violations.append(
                    _violation(
                        "outside-allowed-paths",
                        candidate,
                        None,
                        "path is not in the fix group's allowed paths",
                    )
                )
        if diff.binary:
            violations.append(
                _violation("binary-change", path, None, "binary changes cannot be inspected")
            )
        old_is_test = diff.old_path is not None and path_matches(diff.old_path, test_globs)
        moved_away = diff.new_path is None or diff.new_path != diff.old_path
        if old_is_test and moved_away:
            violations.append(
                _violation(
                    "test-file-deleted", diff.old_path or path, None, "test file deleted or moved"
                )
            )
        is_test = path_matches(path, test_globs)
        if is_test:
            removed = sum(1 for body in diff.removed if any(p.search(body) for p in assertions))
            added = sum(1 for _, body in diff.added if any(p.search(body) for p in assertions))
            if removed > added:
                violations.append(
                    _violation(
                        "test-assertion-removed",
                        path,
                        None,
                        f"{removed - added} assertion lines removed",
                    )
                )
        for line_no, body in diff.added:
            for rule_id, pattern, description in patterns:
                if pattern.search(body):
                    violations.append(_violation(rule_id, path, line_no, description))
    return {"ok": not violations, "violations": violations, "files_checked": len(files)}


def _seq(value: object) -> Sequence[object]:
    return value if isinstance(value, (list, tuple)) else ()


__all__ = ["FileDiff", "evaluate_diff", "glob_to_regex", "parse_unified_diff", "path_matches"]
