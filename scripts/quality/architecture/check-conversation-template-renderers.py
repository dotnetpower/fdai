#!/usr/bin/env python3
"""Reject new regular-expression, keyword-table, and template-answer code in conversation paths."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ALLOWLIST_RELATIVE_PATH = Path(
    "scripts/quality/architecture/conversation-template-renderers-allowlist.json"
)
CONVERSATION_ROOTS = (
    Path("services/core-control-plane/src/fdai/core/conversation"),
    Path("services/core-control-plane/src/fdai_core_service"),
    Path("services/operator-service/src/fdai_operator_service/families/conversation"),
)

REGEX_OR_TEMPLATE_PATTERN = re.compile(
    r"\bdef\s+(?:_?render_[a-z0-9_]*answer|_?format_[a-z0-9_]*answer|build_template_answer)\b"
    r"|\bre\.compile\("
    r"|\b[A-Z0-9_]*(?:KEYWORD|SYNONYM|PHRASE)_TABLE\b"
)


def scan_conversation_paths(root: Path = ROOT) -> tuple[str, ...]:
    """Return sorted relative conversation paths containing template-renderer patterns."""
    detected: list[str] = []
    for rel_dir in CONVERSATION_ROOTS:
        abs_dir = root / rel_dir
        if not abs_dir.is_dir():
            continue
        for path in sorted(abs_dir.rglob("*.py")):
            if "__pycache__" in path.parts or path.is_symlink():
                continue
            source = path.read_text(encoding="utf-8")
            if REGEX_OR_TEMPLATE_PATTERN.search(source) or path.name.endswith("_answer.py"):
                detected.append(path.relative_to(root).as_posix())
    return tuple(sorted(set(detected)))


def load_allowlist(root: Path = ROOT) -> tuple[tuple[str, ...], list[str]]:
    path = root / ALLOWLIST_RELATIVE_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (), [f"conversation allowlist is unreadable: {type(exc).__name__}"]
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return (), ["conversation allowlist MUST declare version 1"]
    raw_paths = payload.get("allowlisted_paths")
    if not isinstance(raw_paths, list) or not all(
        isinstance(item, str) and item.strip() for item in raw_paths
    ):
        return (), ["conversation allowlist allowlisted_paths MUST be a non-empty string list"]
    paths = [str(item) for item in raw_paths]
    errors: list[str] = []
    if paths != sorted(paths):
        errors.append("conversation allowlist paths MUST be sorted")
    if len(paths) != len(set(paths)):
        errors.append("conversation allowlist paths MUST not contain duplicates")
    for rel in paths:
        allowed_prefix = any(
            rel.startswith(f"{conv_root.as_posix()}/") for conv_root in CONVERSATION_ROOTS
        )
        if ".." in Path(rel).parts or not allowed_prefix or not (root / rel).is_file():
            errors.append(f"conversation allowlist path does not exist: {rel}")
    return tuple(paths), errors


def violations(root: Path = ROOT) -> list[str]:
    allowlisted, errors = load_allowlist(root)
    detected = set(scan_conversation_paths(root))
    allowlisted_set = set(allowlisted)

    for added in sorted(detected - allowlisted_set):
        errors.append(
            f"unallowlisted regex/keyword-table/template-answer conversation file: {added}"
        )
    for stale in sorted(allowlisted_set - detected):
        errors.append(
            f"stale conversation template/regex allowlist entry (remove to ratchet L5): {stale}"
        )
    return errors


def main() -> int:
    errs = violations(ROOT)
    if errs:
        for err in errs:
            print(f"conversation-template-renderers: ERROR: {err}", file=sys.stderr)
        return 1
    detected = scan_conversation_paths(ROOT)
    print(f"conversation-template-renderers: OK ({len(detected)} allowlisted L5 legacy file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
