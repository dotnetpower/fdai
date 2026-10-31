"""Fail-closed base synchronization and deterministic hotspot conflict reconciliation."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.automation.developer_workflow_repository import (  # noqa: E402
    git,
    git_common_dir,
)

DEFAULT_BASE_REFS = ("refs/remotes/origin/main", "refs/heads/main")
SERVICE_SUITES_PATH = "tests/integration/service-suites.json"
SERVICE_TEST_GROUPS = frozenset({"unit", "contract", "integration", "smoke"})
LEDGER_PREFIX = "docs/roadmap-implementation/"
ROADMAP_PREFIX = "docs/roadmap/"
RESERVED_TABLE_HEADERS = frozenset(
    {
        ("Area", "State", "Evidence", "Notes"),
        ("Date", "State", "Change", "Evidence", "Remaining"),
    }
)
FM_RE = re.compile(r"\A(---\r?\n)(.*?)(\r?\n---\r?\n)", re.DOTALL)
CONFLICT_MARKER_RE = re.compile(r"^(?:<<<<<<< |=======$|>>>>>>> )", re.MULTILINE)
HUNK_RE = re.compile(
    r"^<<<<<<< [^\n]*\n(?P<ours>.*?)^=======\n(?P<theirs>.*?)^>>>>>>> [^\n]*\n?",
    re.MULTILINE | re.DOTALL,
)


def _load_script_module(name: str, relative_path: str) -> ModuleType:
    existing = sys.modules.get(name)
    if isinstance(existing, ModuleType):
        return existing
    script_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[name] = module
    return module


def _is_valid_ref_token(value: str) -> bool:
    return (
        bool(value)
        and not value.startswith("-")
        and ".." not in value
        and not any(char.isspace() or ord(char) < 32 for char in value)
    )


def resolve_base_ref(repo_root: Path, requested: str | None) -> tuple[str, str] | None:
    """Resolve the requested or default base ref to its ref name and commit SHA."""
    if requested is not None and not _is_valid_ref_token(requested):
        return None
    candidates = (requested,) if requested else DEFAULT_BASE_REFS
    for ref in candidates:
        if not ref:
            continue
        if git(repo_root, "check-ref-format", "--allow-onelevel", ref).returncode != 0:
            continue
        verified = git(repo_root, "rev-parse", "--verify", f"{ref}^{{commit}}")
        if verified.returncode == 0:
            return ref, verified.stdout.strip()
    return None


def _git_blob_text(root: Path, spec: str) -> str | None:
    res = git(root, "show", spec)
    return res.stdout if res.returncode == 0 else None


def _git_blob_sha(root: Path, revision: str, path: str) -> str | None:
    res = git(root, "rev-parse", "--verify", f"{revision}:{path}")
    return res.stdout.strip() if res.returncode == 0 else None


def _front_matter_fields(text: str) -> tuple[dict[str, str], str] | None:
    normalized = text.removeprefix("\ufeff")
    match = FM_RE.match(normalized)
    if match is None:
        return None
    fields: dict[str, str] = {}
    for line in match.group(2).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in line:
            return None
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("\"'")
    return fields, normalized[match.end() :]


def _translation_pair_meta(
    root: Path, revision: str, ko_path: str, src_path: str
) -> dict[str, str] | None:
    ko_text = _git_blob_text(root, f"{revision}:{ko_path}")
    src_sha = _git_blob_sha(root, revision, src_path)
    if ko_text is None or src_sha is None:
        return None
    parsed = _front_matter_fields(ko_text)
    if parsed is None:
        return None
    fields, _ = parsed
    if (
        fields.get("translation_of") != Path(src_path).name
        or fields.get("translation_source_sha") != src_sha
    ):
        return None
    volatile = {"translation_source_sha", "translation_revised"}
    return {k: v for k, v in fields.items() if k not in volatile}


def _rewrite_ko_front_matter(
    fm_block: str,
    body_block: str,
    *,
    source_name: str,
    new_sha: str,
    stamp: str,
) -> str:
    lines = [
        f"translation_of: {source_name}",
        f"translation_source_sha: {new_sha}",
        f"translation_revised: {stamp}",
    ]
    for raw_line in fm_block.splitlines():
        stripped = raw_line.strip()
        if stripped == "---" or not stripped:
            continue
        if stripped.startswith("#"):
            lines.append(stripped)
            continue
        if ":" not in raw_line:
            continue
        key = raw_line.split(":", 1)[0].strip()
        if key not in {"translation_of", "translation_source_sha", "translation_revised"}:
            lines.append(raw_line.rstrip("\r"))
    return "---\n" + "\n".join(lines) + "\n---\n" + body_block


def _safe_worktree_file(root: Path, relative: str) -> Path | None:
    candidate = root / relative
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(root.resolve()):
        return None
    return candidate if candidate.is_file() else None


def _heading_levels(markdown_body: str) -> list[int]:
    levels: list[int] = []
    in_fence = False
    for line in markdown_body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            if 1 <= hashes <= 6 and stripped[hashes : hashes + 1] == " ":
                levels.append(hashes)
    return levels


def _is_in_translation_scope(ko_path: str) -> bool:
    return ko_path == "README-ko.md" or (
        ko_path.startswith("docs/")
        and ko_path.endswith("-ko.md")
        and not ko_path.startswith(("docs/internals/", LEDGER_PREFIX))
    )


def _reconcile_ko_conflict(
    root: Path,
    ko_path: str,
    *,
    head_sha: str,
    base_sha: str,
    unmerged: set[str],
    stamp: str,
) -> bool:
    if not _is_in_translation_scope(ko_path):
        return False
    src_path = f"{ko_path.removesuffix('-ko.md')}.md"
    target_ko = _safe_worktree_file(root, ko_path)
    target_src = _safe_worktree_file(root, src_path)
    if src_path in unmerged or target_ko is None or target_src is None:
        return False
    ours_meta = _translation_pair_meta(root, head_sha, ko_path, src_path)
    theirs_meta = _translation_pair_meta(root, base_sha, ko_path, src_path)
    if ours_meta is None or theirs_meta is None or ours_meta != theirs_meta:
        return False
    working_text = target_ko.read_text(encoding="utf-8")
    closing_match = re.search(r"\r?\n---\r?\n", working_text[3:])
    if not working_text.startswith("---") or closing_match is None:
        return False
    fm_end = 3 + closing_match.end()
    fm_block, body_block = working_text[:fm_end], working_text[fm_end:]
    if CONFLICT_MARKER_RE.search(body_block):
        return False
    src_text = target_src.read_text(encoding="utf-8")
    src_fm = FM_RE.match(src_text)
    src_body = src_text[src_fm.end() :] if src_fm else src_text
    if _heading_levels(src_body) != _heading_levels(body_block):
        return False
    cleaned_fm = HUNK_RE.sub(lambda m: m.group("ours"), fm_block)
    if CONFLICT_MARKER_RE.search(cleaned_fm):
        return False
    new_sha = git(root, "hash-object", src_path).stdout.strip()
    rewritten = _rewrite_ko_front_matter(
        cleaned_fm,
        body_block,
        source_name=Path(src_path).name,
        new_sha=new_sha,
        stamp=stamp,
    )
    target_ko.write_text(rewritten, encoding="utf-8")
    return git(root, "add", "--", ko_path).returncode == 0


def _table_row_cells(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells = tuple(cell.strip() for cell in stripped[1:-1].split("|"))
    if (
        cells in RESERVED_TABLE_HEADERS
        or any(not cell for cell in cells)
        or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)
    ):
        return None
    return cells


def _reconcile_table_hunks(
    section_text: str,
    *,
    expected_columns: int,
    unique_first_col: bool,
) -> str | None:
    def replace_hunk(match: re.Match[str]) -> str:
        ours_lines = [line for line in match.group("ours").splitlines() if line.strip()]
        theirs_lines = [line for line in match.group("theirs").splitlines() if line.strip()]
        ours_rows = [_table_row_cells(line) for line in ours_lines]
        theirs_rows = [_table_row_cells(line) for line in theirs_lines]
        if any(row is None or len(row) != expected_columns for row in ours_rows + theirs_rows):
            raise ValueError("invalid table conflict line")
        valid_ours = [row for row in ours_rows if row is not None]
        valid_theirs = [row for row in theirs_rows if row is not None]
        if unique_first_col:
            ours_by_key = {row[0]: row for row in valid_ours}
            for row in valid_theirs:
                if row[0] in ours_by_key and ours_by_key[row[0]] != row:
                    raise ValueError("conflicting row key state")
        combined = list(ours_lines)
        seen = set(valid_ours)
        for line, row in zip(theirs_lines, valid_theirs, strict=True):
            if row not in seen:
                seen.add(row)
                combined.append(line)
        return "\n".join(combined) + "\n"

    try:
        resolved = HUNK_RE.sub(replace_hunk, section_text)
    except ValueError:
        return None
    if CONFLICT_MARKER_RE.search(resolved):
        return None
    # Deduplicate identical data rows across the whole section while preserving non-row lines.
    deduped_lines: list[str] = []
    seen_rows: set[tuple[str, ...]] = set()
    seen_keys: dict[str, tuple[str, ...]] = {}
    for line in resolved.splitlines():
        row = _table_row_cells(line)
        if row is None or len(row) != expected_columns:
            deduped_lines.append(line)
            continue
        if unique_first_col and row[0] in seen_keys and seen_keys[row[0]] != row:
            return None
        if row in seen_rows:
            continue
        seen_rows.add(row)
        seen_keys[row[0]] = row
        deduped_lines.append(line)
    suffix = "\n" if resolved.endswith("\n") else ""
    return "\n".join(deduped_lines) + suffix


def _reconcile_ledger_conflict(
    root: Path,
    ledger_path: str,
    *,
    head_sha: str,
    base_sha: str,
) -> bool:
    file_path = _safe_worktree_file(root, ledger_path)
    if file_path is None:
        return False
    raw_text = file_path.read_text(encoding="utf-8")
    tracker = _load_script_module(
        "check_roadmap_implementation_tracking",
        "scripts/quality/architecture/check-roadmap-implementation-tracking.py",
    )
    owner_file = _safe_worktree_file(
        root, f"{ROADMAP_PREFIX}{ledger_path.removeprefix(LEDGER_PREFIX)}"
    )
    if owner_file is not None and tracker.has_inline_status(owner_file.read_text(encoding="utf-8")):
        return False
    scope_heading, history_heading, remaining_heading = tracker.SUBSECTION_HEADINGS
    if (
        raw_text.count(scope_heading) != 1
        or raw_text.count(history_heading) != 1
        or raw_text.count(remaining_heading) != 1
    ):
        return False
    before_scope, rest = raw_text.split(scope_heading, 1)
    scope_body, rest = rest.split(history_heading, 1)
    history_body, after_history = rest.split(remaining_heading, 1)
    if CONFLICT_MARKER_RE.search(before_scope) or CONFLICT_MARKER_RE.search(after_history):
        return False
    resolved_scope = _reconcile_table_hunks(scope_body, expected_columns=4, unique_first_col=True)
    resolved_history = _reconcile_table_hunks(
        history_body, expected_columns=5, unique_first_col=False
    )
    if resolved_scope is None or resolved_history is None:
        return False
    resolved_text = (
        f"{before_scope}{scope_heading}{resolved_scope}"
        f"{history_heading}{resolved_history}{remaining_heading}{after_history}"
    )
    for parent_sha in (head_sha, base_sha):
        parent_text = _git_blob_text(root, f"{parent_sha}:{ledger_path}")
        if tracker.ledger_violations(
            resolved_text,
            parent_text,
            relative=ledger_path,
            previous_relative=ledger_path,
        ):
            return False
    parts = tracker._ledger_parts(resolved_text)
    scope_rows, _ = tracker._table_rows(parts[1], tracker.SCOPE_HEADER)
    if any(count > 1 for count in Counter(row[0] for row in scope_rows).values()):
        return False
    file_path.write_text(resolved_text, encoding="utf-8")
    return git(root, "add", "--", ledger_path).returncode == 0


def _reconcile_service_suites_conflict(
    root: Path,
    *,
    merge_base: str,
    head_sha: str,
    base_sha: str,
) -> bool:
    target_suites = _safe_worktree_file(root, SERVICE_SUITES_PATH)
    base_raw = _git_blob_text(root, f"{merge_base}:{SERVICE_SUITES_PATH}")
    ours_raw = _git_blob_text(root, f"{head_sha}:{SERVICE_SUITES_PATH}")
    theirs_raw = _git_blob_text(root, f"{base_sha}:{SERVICE_SUITES_PATH}")
    if target_suites is None or base_raw is None or ours_raw is None or theirs_raw is None:
        return False
    try:
        base_json = json.loads(base_raw)
        ours_json = json.loads(ours_raw)
        theirs_json = json.loads(theirs_raw)
    except json.JSONDecodeError:
        return False
    doc_impact = _load_script_module(
        "check_design_doc_impact",
        "scripts/quality/architecture/check-design-doc-impact.py",
    )
    if not (
        isinstance(base_json, dict)
        and isinstance(ours_json, dict)
        and isinstance(theirs_json, dict)
        and doc_impact.is_additive_service_suites(base_json, ours_json)
        and doc_impact.is_additive_service_suites(base_json, theirs_json)
    ):
        return False
    merged = deepcopy(ours_json)
    for ours_svc, theirs_svc in zip(merged["services"], theirs_json["services"], strict=True):
        if ours_svc.get("id") != theirs_svc.get("id"):
            return False
        for group in SERVICE_TEST_GROUPS:
            target_list = ours_svc["test_groups"][group]
            for item in theirs_svc["test_groups"][group]:
                if item not in target_list:
                    target_list.append(item)
    target_suites.write_text(
        json.dumps(merged, indent=2) + "\n",
        encoding="utf-8",
    )
    return git(root, "add", "--", SERVICE_SUITES_PATH).returncode == 0


def sync_worktree_base(
    root: Path,
    *,
    base_ref: str = "refs/remotes/origin/main",
    fetch: bool = False,
    today: str | None = None,
) -> dict[str, Any]:
    """Synchronize a clean topic worktree with its base and reconcile safe hotspot conflicts."""
    location = git_common_dir(root) if root.is_dir() else None
    if location is None:
        return {
            "reason_code": "git_repository_unavailable",
            "schema_version": 1,
            "status": "blocked",
        }
    repo_root, _common_dir = location
    git_dir = Path(
        git(repo_root, "rev-parse", "--path-format=absolute", "--git-dir").stdout.strip()
    )
    if any(
        (git_dir / marker).exists()
        for marker in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD")
    ):
        return {
            "reason_code": "git_operation_in_progress",
            "schema_version": 1,
            "status": "blocked",
        }
    branch_res = git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch_res.returncode != 0 or not branch_res.stdout.strip():
        return {"reason_code": "detached_head", "schema_version": 1, "status": "blocked"}
    status_res = git(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    if status_res.returncode != 0 or status_res.stdout.strip():
        return {"reason_code": "worktree_dirty", "schema_version": 1, "status": "blocked"}
    if not _is_valid_ref_token(base_ref):
        return {"reason_code": "base_ref_unavailable", "schema_version": 1, "status": "blocked"}
    if fetch and base_ref.startswith("refs/remotes/"):
        parts = base_ref.removeprefix("refs/remotes/").split("/", 1)
        if len(parts) == 2 and all(_is_valid_ref_token(part) for part in parts):
            remote_name, remote_branch = parts
            try:
                fetch_res = subprocess.run(
                    [
                        "git",
                        "fetch",
                        "--quiet",
                        "--",
                        remote_name,
                        f"+refs/heads/{remote_branch}:{base_ref}",
                    ],
                    cwd=repo_root,
                    env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                return {
                    "reason_code": "base_fetch_timeout",
                    "schema_version": 1,
                    "status": "blocked",
                }
            if fetch_res.returncode != 0:
                return {
                    "reason_code": "base_fetch_failed",
                    "schema_version": 1,
                    "status": "blocked",
                }
    resolved_base = resolve_base_ref(repo_root, base_ref)
    if resolved_base is None:
        return {"reason_code": "base_ref_unavailable", "schema_version": 1, "status": "blocked"}
    canonical_base_ref, base_sha = resolved_base
    head_sha = git(repo_root, "rev-parse", "--verify", "HEAD^{commit}").stdout.strip()
    if head_sha == base_sha:
        return {
            "base_ref": canonical_base_ref,
            "base_sha": base_sha,
            "head": head_sha,
            "outcome": "up_to_date",
            "reconciled_paths": [],
            "schema_version": 1,
            "status": "ok",
        }
    counts = git(repo_root, "rev-list", "--left-right", "--count", f"{base_sha}...{head_sha}")
    behind_str, ahead_str = counts.stdout.strip().split()
    behind, ahead = int(behind_str), int(ahead_str)
    if behind == 0:
        return {
            "base_ref": canonical_base_ref,
            "base_sha": base_sha,
            "head": head_sha,
            "outcome": "up_to_date",
            "reconciled_paths": [],
            "schema_version": 1,
            "status": "ok",
        }
    if ahead == 0:
        if git(repo_root, "merge", "--ff-only", "--quiet", base_sha).returncode != 0:
            return {"reason_code": "fast_forward_failed", "schema_version": 1, "status": "blocked"}
        return {
            "base_ref": canonical_base_ref,
            "base_sha": base_sha,
            "head": base_sha,
            "outcome": "fast_forwarded",
            "reconciled_paths": [],
            "schema_version": 1,
            "status": "ok",
        }
    head_tree = git(repo_root, "rev-parse", f"{head_sha}^{{tree}}").stdout.strip()
    base_tree = git(repo_root, "rev-parse", f"{base_sha}^{{tree}}").stdout.strip()
    if head_tree and head_tree == base_tree:
        return {
            "base_ref": canonical_base_ref,
            "base_sha": base_sha,
            "head": head_sha,
            "outcome": "tree_identical_to_base",
            "reconciled_paths": [],
            "schema_version": 1,
            "status": "ok",
        }
    merge_base_res = git(repo_root, "merge-base", head_sha, base_sha)
    if merge_base_res.returncode != 0:
        return {"reason_code": "no_merge_base", "schema_version": 1, "status": "blocked"}
    merge_base = merge_base_res.stdout.strip()
    stamp = today or _dt.date.today().isoformat()
    merge_res = git(repo_root, "merge", "--no-commit", "--no-ff", base_sha)
    reconciled: set[str] = set()
    unmerged_res = git(repo_root, "diff", "--name-only", "--diff-filter=U")
    unmerged = {line for line in unmerged_res.stdout.splitlines() if line}
    if merge_res.returncode != 0 and not unmerged:
        if (git_dir / "MERGE_HEAD").exists():
            git(repo_root, "merge", "--abort")
        return {"reason_code": "merge_failed", "schema_version": 1, "status": "blocked"}

    for path in sorted(unmerged):
        ok = False
        if path.endswith("-ko.md"):
            ok = _reconcile_ko_conflict(
                repo_root,
                path,
                head_sha=head_sha,
                base_sha=base_sha,
                unmerged=unmerged,
                stamp=stamp,
            )
        elif path.startswith(LEDGER_PREFIX) and path.endswith(".md"):
            ok = _reconcile_ledger_conflict(
                repo_root,
                path,
                head_sha=head_sha,
                base_sha=base_sha,
            )
        elif path == SERVICE_SUITES_PATH:
            ok = _reconcile_service_suites_conflict(
                repo_root,
                merge_base=merge_base,
                head_sha=head_sha,
                base_sha=base_sha,
            )
        if not ok:
            git(repo_root, "merge", "--abort")
            return {
                "base_ref": canonical_base_ref,
                "base_sha": base_sha,
                "conflicted_paths": sorted(unmerged),
                "head": head_sha,
                "reason_code": "unresolved_merge_conflict",
                "schema_version": 1,
                "status": "blocked",
            }
        reconciled.add(path)

    commit_res = git(
        repo_root,
        "commit",
        "--no-edit",
        "-m",
        f"Merge {canonical_base_ref} into {branch_res.stdout.strip()}",
    )
    if commit_res.returncode != 0:
        if (git_dir / "MERGE_HEAD").exists():
            git(repo_root, "merge", "--abort")
        return {"reason_code": "merge_commit_failed", "schema_version": 1, "status": "blocked"}
    new_head = git(repo_root, "rev-parse", "--verify", "HEAD^{commit}").stdout.strip()
    return {
        "base_ref": canonical_base_ref,
        "base_sha": base_sha,
        "head": new_head,
        "outcome": "reconciled_merge" if reconciled else "merged",
        "reconciled_paths": sorted(reconciled),
        "schema_version": 1,
        "status": "ok",
    }
