"""Parallel worktree fleet diagnostics and CLI entry point for base synchronization."""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
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
__all__ = ["main", "sync_worktree_base", "worktrees_diagnostic"]


def _status_line_paths(line: str) -> tuple[str, ...]:
    if len(line) <= 3:
        return ()
    raw_path = line[3:]
    if (line[0] in {"R", "C"} or line[1] in {"R", "C"}) and " -> " in raw_path:
        old_path, new_path = raw_path.split(" -> ", 1)
        return (old_path, new_path)
    return (raw_path,)


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


def _parse_worktree_porcelain(output: str) -> tuple[list[dict[str, str]], bool]:
    records: list[dict[str, str]] = []
    for block in output.strip().split("\n\n"):
        if not block.strip():
            continue
        entry: dict[str, str] = {}
        for line in block.splitlines():
            if " " in line:
                key, value = line.split(" ", 1)
                entry[key] = value
        if "worktree" in entry:
            records.append(entry)
    return records[:MAX_WORKTREES], len(records) > MAX_WORKTREES


def _worktree_changed_paths(
    worktree: Path,
    base_sha: str,
    head_sha: str,
    status_lines: list[str],
) -> list[str]:
    paths = {path for line in status_lines for path in _status_line_paths(line) if path}
    committed = git(
        worktree,
        "--no-optional-locks",
        "diff",
        "--name-only",
        "--diff-filter=ACMRTD",
        f"{base_sha}...{head_sha}",
    )
    if committed.returncode == 0:
        paths.update(line for line in committed.stdout.splitlines() if line)
    return sorted(paths)


def _docs_update_targets(repo_root: Path, changed_paths: list[str]) -> list[str]:
    if not changed_paths:
        return []
    manifest_path = repo_root / "scripts" / "lib" / "design-routes.json"
    if not manifest_path.is_file():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
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
    for route in manifest.get("routes", ()):
        if not isinstance(route, dict):
            continue
        required_docs = [str(item) for item in route.get("docs_update", ()) if item]
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
    location = resolved or git_common_dir(root)
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
    raw_entries, truncated = _parse_worktree_porcelain(listing.stdout)
    worktrees: list[dict[str, Any]] = []
    path_owners: dict[str, list[str]] = {}
    doc_owners: dict[str, list[str]] = {}
    behind_active_count = 0
    reclaimable_count = 0

    for index, raw in enumerate(raw_entries):
        wt_path = Path(raw["worktree"])
        if not wt_path.is_dir() or _is_internal_scratch_worktree(wt_path, common_dir):
            continue
        is_primary = index == 0
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
            "--untracked-files=normal",
        )
        status_lines = status_res.stdout.splitlines() if status_res.returncode == 0 else []
        dirty = bool(status_lines)
        counts = git(wt_path, "rev-list", "--left-right", "--count", f"{base_sha}...{head_sha}")
        behind_count = 0
        ahead_count = 0
        if counts.returncode == 0:
            parts = counts.stdout.strip().split()
            if len(parts) == 2:
                behind_count, ahead_count = int(parts[0]), int(parts[1])
        head_tree_res = git(wt_path, "rev-parse", "HEAD^{tree}")
        same_tree = bool(base_tree) and (head_tree_res.stdout.strip() == base_tree)
        reclaimable = not is_primary and not dirty and (ahead_count == 0 or same_tree)
        if reclaimable:
            reclaimable_count += 1
        active = dirty or (ahead_count > 0 and not same_tree)
        if active and behind_count > 0:
            behind_active_count += 1
        changed = (
            _worktree_changed_paths(wt_path, base_sha, head_sha, status_lines) if active else []
        )
        docs_targets = _docs_update_targets(repo_root, changed) if active else []
        wt_label = str(wt_path.resolve())
        for changed_path in changed:
            path_owners.setdefault(changed_path, []).append(wt_label)
        for doc_path in docs_targets:
            doc_owners.setdefault(doc_path, []).append(wt_label)
        worktrees.append(
            {
                "active": active,
                "ahead_count": ahead_count,
                "behind_count": behind_count,
                "branch": branch,
                "changed_path_count": len(changed),
                "changed_paths": changed[:MAX_PATHS],
                "dirty": dirty,
                "docs_update_targets": docs_targets[:MAX_PATHS],
                "head": head_sha,
                "is_primary": is_primary,
                "reclaimable": reclaimable,
                "worktree": wt_label,
            }
        )

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
        "schema_version": 1,
        "status": "warning" if warning else "ok",
        "worktree_count": len(worktrees),
        "worktrees": worktrees,
        "worktrees_truncated": truncated,
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
