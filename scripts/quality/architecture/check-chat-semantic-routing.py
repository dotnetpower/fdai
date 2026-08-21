#!/usr/bin/env python3
"""Block unreviewed lexical natural-language judgment paths."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
BASELINE_RELATIVE_PATH = Path("scripts/quality/architecture/chat-semantic-routing-baseline.json")
BASELINE_KEYS = frozenset({"path", "disposition", "owner", "reason", "issue"})
BASELINE_DISPOSITIONS = frozenset({"migrate", "retain"})
PYTHON_UTTERANCE_NORMALIZATION = re.compile(
    r"\b(?:nl_text|prompt|question|utterance)\s*\.\s*(?:casefold|lower)\s*\("
)
PYTHON_NAMED_LEXICON = re.compile(
    r"_[A-Z0-9_]*(?:CUE|INTENT|KEYWORD|MARKER|MODIFIER|PERSPECTIVE|PHRASE|SYNONYM|VERB)"
    r"[A-Z0-9_]*[^=]*=.*?\bre\.compile\(",
    re.DOTALL,
)
PYTHON_SEMANTIC_MODULE = re.compile(r"\bre\.compile\(")
PYTHON_LEXICAL_CLASSIFIER = re.compile(
    r"\bdef\s+(?:classify_[a-z0-9_]*intent|plan_conversation_tools)\s*\("
)
TYPESCRIPT_LEXICAL_ROUTER = re.compile(
    r"\b(?:const\s+(?:ACTION_SYNONYMS|SIGNAL_KEYWORDS)|function\s+suggestDraftFromText)\b|"
    r"/(?:[^/\\]|\\.)+/[dgimsuvy]*\.test\(\s*"
    r"(?:q|question|text|message|prompt|utterance|norm|normalized|lowered)\b"
)
TYPESCRIPT_NORMALIZATION = re.compile(r"\.to(?:Locale)?LowerCase\s*\(")
TYPESCRIPT_LITERAL_INCLUDES = re.compile(r"\.includes\s*\(\s*['\"]")


def _python_lexical_ast(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    compile_aliases = {"compile"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "re":
            compile_aliases.update(
                alias.asname or alias.name for alias in node.names if alias.name == "compile"
            )
    for function in (
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        if _function_has_lexical_judgment(function, compile_aliases=compile_aliases):
            return True
    return False


def _function_has_lexical_judgment(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    compile_aliases: set[str],
) -> bool:
    semantic_name = re.search(
        r"(?:answer|classif|compile|decide|intent|introspect|question|route|semantic|suggest)",
        function.name,
    )
    if semantic_name is None:
        return False
    derived = {
        argument.arg
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    }
    changed = True
    while changed:
        changed = False
        for node in ast.walk(function):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None or not _derived_from_input(value, derived):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in derived:
                    derived.add(target.id)
                    changed = True
    for node in ast.walk(function):
        if isinstance(node, ast.Compare) and _lexical_membership(node, derived):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"search", "match", "fullmatch"} and any(
                _derived_from_input(argument, derived) for argument in node.args
            ):
                return True
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        called = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else ""
        )
        if called in compile_aliases and node.args and isinstance(node.args[0], ast.Constant):
            return True
    return False


def _derived_from_input(node: ast.AST, derived: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in derived
    if isinstance(node, (ast.Call, ast.Attribute, ast.Subscript, ast.UnaryOp)):
        return any(_derived_from_input(child, derived) for child in ast.iter_child_nodes(node))
    if isinstance(node, (ast.BinOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.JoinedStr)):
        return any(_derived_from_input(child, derived) for child in ast.iter_child_nodes(node))
    return False


def _lexical_membership(node: ast.Compare, derived: set[str]) -> bool:
    operands = (node.left, *node.comparators)
    if not any(isinstance(operator, (ast.In, ast.NotIn)) for operator in node.ops):
        return False
    has_literal = any(
        isinstance(item, ast.Constant) and isinstance(item.value, str)
        for operand in operands
        for item in ast.walk(operand)
    )
    return has_literal and any(_derived_from_input(operand, derived) for operand in operands)


def _production_roots(root: Path) -> tuple[Path, ...]:
    roots = [root / "console" / "src", root / "cli" / "src"]
    roots.extend(
        source_root
        for parent in (root / "services", root / "packages")
        if parent.is_dir()
        for package in sorted(parent.iterdir())
        if (source_root := package / "src").is_dir()
    )
    return tuple(path for path in roots if path.is_dir())


def _lexical_semantic_paths(root: Path = ROOT) -> tuple[str, ...]:
    detected: set[str] = set()
    for source_root in _production_roots(root):
        if not source_root.is_dir():
            continue
        for path in source_root.rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx"} or path.name.endswith(".test.ts"):
                continue
            source = path.read_text(encoding="utf-8")
            if path.suffix == ".py":
                lexical = bool(
                    _python_lexical_ast(source)
                    or PYTHON_UTTERANCE_NORMALIZATION.search(source)
                    or PYTHON_NAMED_LEXICON.search(source)
                    or PYTHON_LEXICAL_CLASSIFIER.search(source)
                    or (
                        path.name.startswith("semantic_")
                        and PYTHON_SEMANTIC_MODULE.search(source)
                        and "utterance" in source
                    )
                    or "class DeterministicPatternCompiler" in source
                )
            else:
                lexical = bool(
                    TYPESCRIPT_LEXICAL_ROUTER.search(source)
                    or (
                        TYPESCRIPT_NORMALIZATION.search(source)
                        and TYPESCRIPT_LITERAL_INCLUDES.search(source)
                    )
                )
            if lexical:
                detected.add(path.relative_to(root).as_posix())
    return tuple(sorted(detected))


def _baseline(root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    path = root / BASELINE_RELATIVE_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"semantic baseline is unreadable: {type(exc).__name__}"]
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return {}, ["semantic baseline MUST declare version 1"]
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return {}, ["semantic baseline candidates MUST be a list"]
    entries: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or set(candidate) != BASELINE_KEYS:
            failures.append(f"semantic baseline candidate {index} has an invalid schema")
            continue
        relative = candidate.get("path")
        disposition = candidate.get("disposition")
        owner = candidate.get("owner")
        reason = candidate.get("reason")
        issue = candidate.get("issue")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            failures.append(f"semantic baseline candidate {index} has an invalid path")
            continue
        if relative in entries:
            failures.append(f"semantic baseline path is duplicated: {relative}")
            continue
        if disposition not in BASELINE_DISPOSITIONS:
            failures.append(f"semantic baseline disposition is invalid: {relative}")
        if not isinstance(owner, str) or not owner.strip():
            failures.append(f"semantic baseline owner is missing: {relative}")
        if not isinstance(reason, str) or len(reason.strip()) < 20:
            failures.append(f"semantic baseline reason is too short: {relative}")
        if issue != 252:
            failures.append(f"semantic baseline issue must be 252: {relative}")
        if ".." in Path(relative).parts or not (root / relative).is_file():
            failures.append(f"semantic baseline path does not exist: {relative}")
        entries[relative] = candidate
    if list(entries) != sorted(entries):
        failures.append("semantic baseline candidates MUST be sorted by path")
    return entries, failures


def violations(root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    deck = root / "console" / "src" / "deck"
    for name in ("action-intent.ts", "action-intent.test.ts"):
        if (deck / name).exists():
            failures.append(f"client natural-language router returned: console/src/deck/{name}")

    submit_hook = deck / "use-command-deck-submit.ts"
    if submit_hook.is_file():
        submit_source = submit_hook.read_text(encoding="utf-8")
        for token in ("detectActionIntent", "submitAction("):
            if token in submit_source:
                failures.append(
                    f"client submit path contains forbidden natural-language branch: {token}"
                )

    baseline, baseline_failures = _baseline(root)
    failures.extend(baseline_failures)
    detected = set(_lexical_semantic_paths(root))
    failures.extend(
        f"unreviewed lexical semantic judgment path: {path}"
        for path in sorted(detected - baseline.keys())
    )
    failures.extend(
        f"stale lexical semantic baseline path: {path}"
        for path in sorted(baseline.keys() - detected)
    )
    return failures


def main() -> int:
    failures = violations()
    if failures:
        for failure in failures:
            print(f"chat-semantic-routing: ERROR: {failure}", file=sys.stderr)
        return 1
    print("chat-semantic-routing: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
