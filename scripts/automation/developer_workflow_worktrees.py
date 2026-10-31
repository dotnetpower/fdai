"""Parallel worktree fleet diagnostics and CLI entry point for base synchronization."""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.automation.developer_workflow_repository import (  # noqa: E402
    MAX_PATHS,
    RepositoryLocation,
    git,
    git_common_dir,
)
from scripts.automation.parallel_worktree_reconcile import (  # noqa: E402
    _load_script_module,
    sync_worktree_base,
)
from scripts.automation.parallel_worktree_reconcile import (  # noqa: E402
    resolve_base_ref as _resolve_base_ref,
)

MAX_WORKTREES = 64
__all__ = [
    "main",
    "prune_reclaimable_worktrees",
    "sync_worktree_base",
    "worktrees_diagnostic",
]


def _status_line_paths(line: str) -> tuple[str, ...]:
    if len(line) <= 3:
        return ()
    raw_path = line[3:]
    if (line[0] in {"R", "C"} or line[1] in {"R", "C"}) and " -> " in raw_path:
        old_path, new_path = raw_path.split(" -> ", 1)
        return (old_path.strip('"'), new_path.strip('"'))
    return (raw_path.strip('"'),)


def _parse_status_z(output: str) -> list[str]:
    tokens = output.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(tokens):
        entry = tokens[index]
        if len(entry) > 3:
            paths.append(entry[3:])
            if entry[0] in {"R", "C"} or entry[1] in {"R", "C"}:
                index += 1
                if index < len(tokens) and tokens[index]:
                    paths.append(tokens[index])
        index += 1
    return paths


def _is_internal_scratch_worktree(path: Path, common_dir: Path) -> bool:
    resolved = path.resolve()
    for internal_name in ("fdai-local-validation", "fdai-validation-queue"):
        if resolved.is_relative_to((common_dir / internal_name).resolve()):
            return True
    parts = resolved.parts
    return any(
        parts[index] == ".fdai" and parts[index + 1].startswith("local-validation-")
        for index in range(len(parts) - 1)
    )


def _parse_worktree_porcelain(output: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for block in output.strip().split("\n\n"):
        if not block.strip():
            continue
        entry: dict[str, str] = {}
        for line in block.splitlines():
            if line == "locked" or line.startswith("locked "):
                entry["locked"] = "true"
            elif " " in line:
                key, value = line.split(" ", 1)
                entry[key] = value
        if "worktree" in entry:
            records.append(entry)
    return records


def _worktree_changed_paths(
    worktree: Path,
    base_sha: str,
    head_sha: str,
    dirty_paths: list[str],
) -> list[str]:
    paths = {path for path in dirty_paths if path}
    if head_sha and head_sha != base_sha:
        committed = git(
            worktree,
            "--no-optional-locks",
            "diff",
            "-z",
            "--name-only",
            "--diff-filter=ACMRTD",
            f"{base_sha}...{head_sha}",
        )
        if committed.returncode == 0:
            paths.update(item for item in committed.stdout.split("\0") if item)
    return sorted(paths)


def _canonical_hotspot_doc(path: str) -> str:
    if path.endswith("-ko.md"):
        path = f"{path.removesuffix('-ko.md')}.md"
    if path.startswith("docs/roadmap-implementation/") and path.endswith(".md"):
        return f"docs/roadmap/{path.removeprefix('docs/roadmap-implementation/')}"
    return path


def _docs_update_targets(
    repo_root: Path,
    changed_paths: list[str],
    *,
    manifest: dict[str, Any] | None = None,
) -> list[str]:
    if not changed_paths:
        return []
    loaded_manifest = manifest
    if loaded_manifest is None:
        manifest_path = repo_root / "scripts" / "lib" / "design-routes.json"
        if not manifest_path.is_file():
            return []
        try:
            loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
    if not isinstance(loaded_manifest, dict):
        return []
    doc_impact = _load_script_module(
        "check_design_doc_impact",
        "scripts/quality/architecture/check-design-doc-impact.py",
    )
    behavior_paths = [
        path
        for path in changed_paths
        if path not in doc_impact.DERIVED_OUTPUT_PATHS and not doc_impact.is_test_support_only(path)
    ]
    if not behavior_paths:
        return []
    docs: set[str] = set()
    for route in loaded_manifest.get("routes", ()):
        if not isinstance(route, dict):
            continue
        required_docs = [
            _canonical_hotspot_doc(str(item)) for item in route.get("docs_update", ()) if item
        ]
        if not required_docs:
            continue
        patterns = tuple(route.get("paths", ())) + tuple(route.get("optional_paths", ()))
        if any(
            pattern == "**" or fnmatch.fnmatchcase(candidate, str(pattern))
            for path in behavior_paths
            for candidate in doc_impact._route_paths(path)
            for pattern in patterns
        ):
            docs.update(required_docs)
    return sorted(docs)


def worktrees_diagnostic(
    root: Path,
    *,
    base_ref: str | None = None,
    resolved: RepositoryLocation | None = None,
) -> dict[str, Any]:
    """Inspect registered worktrees for base drift, reclaimable state, and hotspot collisions."""
    location = (resolved or git_common_dir(root)) if root.is_dir() else None
    if location is None:
        return {
            "read_only": True,
            "reason_code": "git_repository_unavailable",
            "schema_version": 1,
            "status": "unavailable",
        }
    repo_root, common_dir = location
    resolved_base = _resolve_base_ref(repo_root, base_ref)
    if resolved_base is None:
        return {
            "read_only": True,
            "reason_code": "base_ref_unavailable",
            "schema_version": 1,
            "status": "unavailable",
        }
    canonical_base_ref, base_sha = resolved_base
    base_tree_res = git(repo_root, "rev-parse", f"{base_sha}^{{tree}}")
    base_tree = base_tree_res.stdout.strip() if base_tree_res.returncode == 0 else ""
    listing = git(repo_root, "worktree", "list", "--porcelain")
    if listing.returncode != 0:
        return {
            "read_only": True,
            "reason_code": "worktree_list_unavailable",
            "schema_version": 1,
            "status": "unavailable",
        }
    all_entries = [
        raw
        for raw in _parse_worktree_porcelain(listing.stdout)
        if Path(raw["worktree"]).is_dir()
        and not _is_internal_scratch_worktree(Path(raw["worktree"]), common_dir)
    ]
    truncated = len(all_entries) > MAX_WORKTREES
    raw_entries = all_entries[:MAX_WORKTREES]
    manifest_path = repo_root / "scripts" / "lib" / "design-routes.json"
    cached_manifest: dict[str, Any] | None = None
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cached_manifest = loaded
        except (OSError, json.JSONDecodeError):
            cached_manifest = None

    worktrees: list[dict[str, Any]] = []
    path_owners: dict[str, list[str]] = {}
    doc_owners: dict[str, list[str]] = {}
    reclaimable_worktrees: list[str] = []
    behind_active_count = 0
    reclaimable_count = 0

    def _inspect_one(
        item: tuple[int, dict[str, str]],
    ) -> tuple[dict[str, Any], list[str], list[str], str | None]:
        index, raw = item
        wt_path = Path(raw["worktree"])
        is_primary = index == 0
        is_locked = raw.get("locked") == "true"
        head_sha = raw.get("HEAD", "")
        branch_ref = raw.get("branch", "")
        branch = (
            branch_ref.removeprefix("refs/heads/")
            if branch_ref.startswith("refs/heads/")
            else "detached"
        )
        status_res = git(
            wt_path,
            "--no-optional-locks",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=normal",
        )
        dirty_paths = _parse_status_z(status_res.stdout) if status_res.returncode == 0 else []
        dirty = bool(dirty_paths)
        behind_count = 0
        ahead_count = 0
        if head_sha and head_sha != base_sha:
            counts = git(wt_path, "rev-list", "--left-right", "--count", f"{base_sha}...{head_sha}")
            if counts.returncode == 0:
                parts = counts.stdout.strip().split()
                if len(parts) == 2:
                    behind_count, ahead_count = int(parts[0]), int(parts[1])
        if head_sha == base_sha:
            same_tree = True
        elif ahead_count > 0 and base_tree:
            head_tree_res = git(wt_path, "rev-parse", "HEAD^{tree}")
            same_tree = head_tree_res.stdout.strip() == base_tree
        else:
            same_tree = False
        reclaimable = (
            not is_primary and not is_locked and not dirty and (ahead_count == 0 or same_tree)
        )
        wt_label = str(wt_path.resolve())
        active = dirty or (ahead_count > 0 and not same_tree)
        changed = (
            _worktree_changed_paths(wt_path, base_sha, head_sha, dirty_paths) if active else []
        )
        record = {
            "active": active,
            "ahead_count": ahead_count,
            "behind_count": behind_count,
            "branch": branch,
            "changed_path_count": len(changed),
            "changed_paths": changed[:MAX_PATHS],
            "dirty": dirty,
            "docs_update_targets": [],
            "head": head_sha,
            "is_primary": is_primary,
            "locked": is_locked,
            "reclaimable": reclaimable,
            "worktree": wt_label,
        }
        return record, changed, [], (wt_label if reclaimable else None)

    indexed_entries = list(enumerate(raw_entries))
    if len(indexed_entries) > 1:
        with ThreadPoolExecutor(max_workers=min(8, len(indexed_entries))) as pool:
            inspected = list(pool.map(_inspect_one, indexed_entries))
    else:
        inspected = [_inspect_one(item) for item in indexed_entries]

    for record, changed, _unused_docs, reclaim_label in inspected:
        wt_label = str(record["worktree"])
        docs_targets = (
            _docs_update_targets(repo_root, changed, manifest=cached_manifest)
            if record["active"]
            else []
        )
        record["docs_update_targets"] = docs_targets[:MAX_PATHS]
        if reclaim_label is not None:
            reclaimable_count += 1
            reclaimable_worktrees.append(reclaim_label)
        if record["active"] and int(record["behind_count"]) > 0:
            behind_active_count += 1
        for changed_path in changed:
            path_owners.setdefault(changed_path, []).append(wt_label)
        for doc_path in docs_targets:
            doc_owners.setdefault(doc_path, []).append(wt_label)
        worktrees.append(record)

    path_collisions = [
        {"path": path, "worktrees": sorted(owners)}
        for path, owners in sorted(path_owners.items())
        if len(owners) > 1
    ][:MAX_PATHS]
    hotspot_doc_collisions = [
        {"document": doc, "worktrees": sorted(owners)}
        for doc, owners in sorted(doc_owners.items())
        if len(owners) > 1
    ][:MAX_PATHS]
    warning = bool(path_collisions or hotspot_doc_collisions or behind_active_count > 0)
    return {
        "active_worktree_count": sum(1 for item in worktrees if item["active"]),
        "base_ref": canonical_base_ref,
        "base_sha": base_sha,
        "behind_active_count": behind_active_count,
        "hotspot_doc_collision_count": sum(1 for owners in doc_owners.values() if len(owners) > 1),
        "hotspot_doc_collisions": hotspot_doc_collisions,
        "path_collision_count": sum(1 for owners in path_owners.values() if len(owners) > 1),
        "path_collisions": path_collisions,
        "read_only": True,
        "reclaimable_count": reclaimable_count,
        "reclaimable_worktrees": reclaimable_worktrees[:MAX_PATHS],
        "schema_version": 1,
        "status": "warning" if warning else "ok",
        "worktree_count": len(worktrees),
        "worktrees": worktrees,
        "worktrees_truncated": truncated,
    }


def prune_reclaimable_worktrees(
    root: Path,
    *,
    base_ref: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Preview or remove clean, unlocked, already-merged non-primary worktrees."""
    diag = worktrees_diagnostic(root, base_ref=base_ref)
    if diag["status"] == "unavailable":
        return {
            "apply": apply,
            "pruned_worktrees": [],
            "reason_code": diag["reason_code"],
            "schema_version": 1,
            "status": "blocked",
        }
    current_top_res = git(root, "rev-parse", "--show-toplevel")
    current_top = (
        str(Path(current_top_res.stdout.strip()).resolve())
        if current_top_res.returncode == 0
        else str(root.resolve())
    )
    candidates = [
        str(item["worktree"])
        for item in diag["worktrees"]
        if item.get("reclaimable") and item.get("worktree") != current_top
    ]
    pruned: list[str] = []
    if apply:
        for wt_str in candidates:
            if git(root, "worktree", "remove", wt_str).returncode == 0:
                pruned.append(wt_str)
    return {
        "apply": apply,
        "candidate_count": len(candidates),
        "candidate_worktrees": candidates[:MAX_PATHS],
        "pruned_count": len(pruned),
        "pruned_worktrees": pruned[:MAX_PATHS],
        "schema_version": 1,
        "status": "ok",
    }


def main(argv: list[str] | None = None) -> int:
    """Run worktree fleet diagnostics or explicit base synchronization."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--base", default=None, dest="base_ref")
    status_parser.add_argument("--json", action="store_true", dest="as_json")
    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--base", default="refs/remotes/origin/main", dest="base_ref")
    sync_parser.add_argument("--fetch", action="store_true")
    sync_parser.add_argument("--json", action="store_true", dest="as_json")
    prune_parser = subparsers.add_parser("prune")
    prune_parser.add_argument("--base", default=None, dest="base_ref")
    prune_parser.add_argument("--apply", action="store_true")
    prune_parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    if args.command == "status":
        report = worktrees_diagnostic(Path.cwd(), base_ref=args.base_ref)
        if args.as_json:
            print(json.dumps(report, sort_keys=True))
        else:
            print(
                f"worktrees: status={report['status']} count={report.get('worktree_count', 0)} "
                f"active={report.get('active_worktree_count', 0)} "
                f"reclaimable={report.get('reclaimable_count', 0)}"
            )
        return 0 if report["status"] != "unavailable" else 1
    if args.command == "prune":
        report = prune_reclaimable_worktrees(Path.cwd(), base_ref=args.base_ref, apply=args.apply)
        if args.as_json:
            print(json.dumps(report, sort_keys=True))
        else:
            print(
                f"prune-worktrees: status={report['status']} "
                f"candidates={report.get('candidate_count', 0)} "
                f"pruned={report.get('pruned_count', 0)}"
            )
        return 0 if report["status"] == "ok" else 1
    report = sync_worktree_base(Path.cwd(), base_ref=args.base_ref, fetch=args.fetch)
    if args.as_json:
        print(json.dumps(report, sort_keys=True))
    elif report["status"] == "ok":
        print(
            f"sync-worktree: status=ok outcome={report['outcome']} "
            f"head={str(report['head'])[:12]} reconciled={len(report['reconciled_paths'])}"
        )
    else:
        print(
            f"sync-worktree: BLOCKED reason={report['reason_code']}",
            file=sys.stderr,
        )
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
