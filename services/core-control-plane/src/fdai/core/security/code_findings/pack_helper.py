#!/usr/bin/env python3
"""FDAI remediation-pack helper (standard library only).

A developer's coding agent (GitHub Copilot, Claude Code, or another tool) runs this helper while it
follows the pack's ``REMEDIATE.prompt.md``. The helper turns the steps that must be exact into
deterministic commands, so they do not depend on model behavior:

``verify``         check file digests, expiry, base commit ancestry, a clean tree, and resume state
``summary``        count issues by priority, severity, and confidence; list coverage limits
``plan``           list the fix groups selected by the recorded scope, in order
``next-group``     return the next pending fix group with its effective depth
``start``          create or reuse the remediation branch and record the starting commit
``record``         record the scope, a group start or end, or an issue status in the ledger
``guard``          check the group's changes against the remediation policy
``commit``         run the guard and commit the group's changes with FDAI trailers
``rollback-group`` restore the commit recorded at the group's start (requires ``--yes``)
``finish``         write ``result/remediation-result.json`` for upload to FDAI

Every command prints one JSON object and exits non-zero when ``ok`` is false. The helper never
pushes, never contacts a network host, and never edits files itself except the pack's ledger and
result files and the git operations listed above. FDAI re-checks every claim on import.

This module ships in each pack as ``tools/fdai_remediate.py`` next to ``tools/fdai_diff_guard.py``
and ``tools/fdai_pack_runtime.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdai.core.security.code_findings import diff_guard as guard
    from fdai.core.security.code_findings import pack_runtime as rt
else:
    try:  # remediation-pack layout: sibling modules in tools/
        import fdai_diff_guard as guard
        import fdai_pack_runtime as rt
    except ImportError:  # FDAI source tree
        from fdai.core.security.code_findings import diff_guard as guard
        from fdai.core.security.code_findings import pack_runtime as rt


def cmd_start(pack: rt.Pack, repo: Path) -> dict[str, Any]:
    rt.require_scope(pack)
    rt.require_pack_ignored(pack, repo)
    if rt.dirty_paths(pack, repo):
        raise rt.HelperError("working tree must be clean before starting")
    ledger = pack.ledger()
    current = rt.git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if ledger.get("branch") and ledger["branch"] == current:
        return {"ok": True, "branch": current, "reused": True}
    name, suffix = f"fdai/sec/{pack.pack_id}", 1
    while (
        rt.git(
            repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}", check=False
        ).returncode
        == 0
    ):
        suffix += 1
        name = f"fdai/sec/{pack.pack_id}-{suffix}"
    rt.git(repo, "switch", "-c", name)
    ledger.update(branch=name, start_head=rt.head(repo))
    ledger["session"] = {"started_at": rt.now_utc().isoformat(), "groups_finished": 0}
    pack.save(rt.LEDGER, ledger)
    return {"ok": True, "branch": name, "start_head": ledger["start_head"], "reused": False}


def cmd_record(pack: rt.Pack, repo: Path, args: argparse.Namespace) -> dict[str, Any]:
    ledger = pack.ledger()
    issue_ids = {issue["issue_id"] for issue in pack.index()["issues"]}
    if args.kind == "scope":
        scope = dict(rt.RECOMMENDED_SCOPE) if args.recommended else json.loads(args.json or "{}")
        scope = {**rt.RECOMMENDED_SCOPE, **scope}
        for key, allowed in rt.SCOPE_CHOICES.items():
            if scope[key] not in allowed:
                raise rt.HelperError(f"scope.{key} must be one of {', '.join(allowed)}")
        scope["ids"] = [
            i for i in scope.get("ids", []) if isinstance(i, str) and rt.ID_PATTERN.match(i)
        ]
        unknown = set(scope) - set(rt.SCOPE_CHOICES) - {"ids", "tests"}
        if unknown:
            raise rt.HelperError(f"unknown scope keys: {', '.join(sorted(unknown))}")
        ledger["scope"] = scope
        ledger["session"] = {"started_at": rt.now_utc().isoformat(), "groups_finished": 0}
    elif args.kind == "group-start":
        pack.group(args.target)
        if rt.dirty_paths(pack, repo):
            raise rt.HelperError("working tree must be clean at a group start")
        ledger["groups"][args.target] = {
            "status": "in_progress",
            "start_head": rt.head(repo),
            "commits": [],
        }
    elif args.kind == "group-end":
        if args.status not in ("done", "failed", "skipped"):
            raise rt.HelperError("group status must be done, failed, or skipped")
        group = ledger["groups"].setdefault(args.target, {"commits": []})
        group["status"] = args.status
        ledger["session"]["groups_finished"] += 1
    elif args.kind == "issue":
        if args.target not in issue_ids:
            raise rt.HelperError("issue id is not in this pack")
        if args.status not in rt.ISSUE_STATUSES or (
            args.validation and args.validation not in rt.VALIDATIONS
        ):
            raise rt.HelperError(f"status must be one of {', '.join(rt.ISSUE_STATUSES)}")
        entry = ledger["issues"].setdefault(args.target, {"commits": [], "regression_tests": []})
        entry.update(
            status=args.status,
            validation=args.validation or entry.get("validation", "not_run"),
            evidence=rt.clean_text(args.evidence, 2000),
            tests=rt.clean_text(args.tests, 500),
        )
        entry["regression_tests"] = sorted(
            {*entry["regression_tests"], *(args.regression_test or [])}
        )
    else:
        raise rt.HelperError("record kind must be scope, group-start, group-end, or issue")
    pack.save(rt.LEDGER, ledger)
    return {"ok": True, "recorded": args.kind}


def _group_diff(pack: rt.Pack, repo: Path, group_id: str) -> str:
    """Return the group's full change since its start, including untracked files.

    Renames are split into delete plus add so moved tests and out-of-scope sources stay visible.
    A failing untracked-file diff aborts instead of silently hiding that file from the guard.
    """
    start = pack.ledger()["groups"].get(group_id, {}).get("start_head")
    if not start:
        raise rt.HelperError("record group-start before guarding or committing a group")
    start = rt.commit_ref(start, "group start_head")
    quiet = ("-c", "core.quotePath=false")
    diff = rt.git(repo, *quiet, "diff", "--no-color", "--no-ext-diff", "--no-renames", start).stdout
    for path in rt.untracked_paths(pack, repo):
        proc = rt.git(
            repo, *quiet, "diff", "--no-color", "--no-index", "--", "/dev/null", path, check=False
        )
        if proc.returncode not in (0, 1):
            raise rt.HelperError(f"cannot diff untracked file {path!r}; resolve it by hand")
        diff += proc.stdout
    return diff


def cmd_guard(pack: rt.Pack, repo: Path, group_id: str) -> dict[str, Any]:
    tampered = rt.tampered_files(pack)
    if tampered:
        raise rt.HelperError(f"pack files changed since export: {', '.join(tampered[:5])}")
    group = pack.group(group_id)
    report = guard.evaluate_diff(
        _group_diff(pack, repo, group_id), group["allowed_paths"], pack.policy()
    )
    return {**report, "group_id": group_id}


def cmd_commit(pack: rt.Pack, repo: Path, group_id: str, issues: list[str]) -> dict[str, Any]:
    group = pack.group(group_id)
    report = cmd_guard(pack, repo, group_id)
    if not report["ok"]:
        return {**report, "committed": False}
    rt.require_pack_ignored(pack, repo)
    finding_ids = [i for i in (issues or group["issue_ids"]) if i in group["issue_ids"]]
    inside = rt.pack_rel(pack, repo)
    rt.git(repo, "add", "-A", "--", ".", *([f":(exclude){inside}"] if inside else []))
    if not rt.git(repo, "diff", "--cached", "--name-only").stdout.strip():
        return {"ok": True, "committed": False, "detail": "nothing to commit"}
    message = f"fix(security): remediate {group['weakness_class']} ({group_id})"
    trailers = f"FDAI-Pack: {pack.pack_id}\nFDAI-Finding: {', '.join(finding_ids)}"
    rt.git(repo, "commit", "-m", message, "-m", trailers)
    sha = rt.head(repo)
    ledger = pack.ledger()
    ledger["groups"][group_id]["commits"].append(sha)
    for issue_id in finding_ids:
        ledger["issues"].setdefault(issue_id, {"commits": [], "regression_tests": []})[
            "commits"
        ].append(sha)
    pack.save(rt.LEDGER, ledger)
    return {"ok": True, "committed": True, "commit": sha, "issue_ids": finding_ids}


def cmd_rollback(pack: rt.Pack, repo: Path, group_id: str, yes: bool) -> dict[str, Any]:
    if not yes:
        raise rt.HelperError("rollback-group discards the group's changes; rerun with --yes")
    group = pack.group(group_id)
    ledger = pack.ledger()
    start = rt.commit_ref(ledger["groups"].get(group_id, {}).get("start_head"), "group start")
    if rt.git(repo, "merge-base", "--is-ancestor", start, "HEAD", check=False).returncode:
        raise rt.HelperError("group start is not an ancestor of HEAD")
    for body in rt.git(repo, "log", "--format=%B%x1e", f"{start}..HEAD").stdout.split("\x1e"):
        if body.strip() and f"FDAI-Pack: {pack.pack_id}" not in body:
            raise rt.HelperError(
                "a commit after the group start is not from this pack; roll back by hand"
            )
    rt.git(repo, "reset", "--hard", start)
    removed, skipped = [], []
    top = repo.resolve()
    for path in rt.untracked_paths(pack, repo):
        if not guard.path_matches(path, group["allowed_paths"]):
            continue
        target = top / path
        if target.is_symlink() or not target.resolve().is_relative_to(top):
            skipped.append(path)
            continue
        target.unlink(missing_ok=True)
        removed.append(path)
    ledger["groups"][group_id].update(status="failed", commits=[])
    ledger["session"]["groups_finished"] += 1
    pack.save(rt.LEDGER, ledger)
    return {
        "ok": True,
        "restored": start,
        "removed_untracked": removed,
        "skipped_untracked": skipped,
    }


def cmd_finish(pack: rt.Pack, repo: Path) -> dict[str, Any]:
    ledger = pack.ledger()
    issues = []
    for issue in pack.index()["issues"]:
        entry = ledger["issues"].get(issue["issue_id"], {})
        issues.append(
            {
                "issue_id": issue["issue_id"],
                "status": entry.get("status", "not_attempted"),
                "validation": entry.get("validation", "not_run"),
                "commits": [c for c in entry.get("commits", []) if rt.SHA_PATTERN.match(c)],
                "evidence": entry.get("evidence", ""),
                "tests": entry.get("tests", ""),
                "regression_tests": entry.get("regression_tests", []),
            }
        )
    result = {
        "schema_version": 1,
        "pack_id": pack.pack_id,
        "manifest_sha256": pack.manifest_sha256,
        "base_commit": pack.manifest["repository"]["base_commit"],
        "final_head": rt.head(repo),
        "branch": ledger.get("branch"),
        "helper_version": rt.HELPER_VERSION,
        "scope": ledger.get("scope"),
        "completed_at": rt.now_utc().isoformat(),
        "issues": issues,
    }
    pack.save(rt.RESULT, result)
    counts: dict[str, int] = {}
    for item in issues:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "ok": True,
        "result_path": str(pack.root / rt.RESULT),
        "status_counts": counts,
        "upload_instructions": pack.manifest.get("upload_instructions", ""),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fdai_remediate", description="FDAI remediation-pack helper"
    )
    parser.add_argument("--pack", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--repo", default=".")
    parser.add_argument("--trusted-key", help="FDAI pack-signing public key (PEM or 64-hex)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("verify", "summary", "plan", "next-group", "start", "finish"):
        sub.add_parser(name)
    record = sub.add_parser("record")
    record.add_argument("kind", choices=("scope", "group-start", "group-end", "issue"))
    record.add_argument("target", nargs="?", default="")
    record.add_argument("--recommended", action="store_true")
    record.add_argument("--json")
    record.add_argument("--status", default="")
    record.add_argument("--validation", default="")
    record.add_argument("--evidence", default="")
    record.add_argument("--tests", default="")
    record.add_argument("--regression-test", action="append")
    for name in ("guard", "commit", "rollback-group"):
        command = sub.add_parser(name)
        command.add_argument("group")
        if name == "commit":
            command.add_argument("--issue", action="append", default=[])
        if name == "rollback-group":
            command.add_argument("--yes", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        # Every git call runs at the repository top level so paths are root-relative.
        pack, repo = rt.Pack(Path(args.pack)), rt.repo_root(Path(args.repo).resolve())
        handlers = {
            "verify": lambda: rt.cmd_verify(pack, repo, args.trusted_key),
            "summary": lambda: rt.cmd_summary(pack),
            "plan": lambda: rt.cmd_plan(pack),
            "next-group": lambda: rt.cmd_next_group(pack),
            "start": lambda: cmd_start(pack, repo),
            "record": lambda: cmd_record(pack, repo, args),
            "guard": lambda: cmd_guard(pack, repo, args.group),
            "commit": lambda: cmd_commit(pack, repo, args.group, args.issue),
            "rollback-group": lambda: cmd_rollback(pack, repo, args.group, args.yes),
            "finish": lambda: cmd_finish(pack, repo),
        }
        result = handlers[args.command]()
    except (rt.HelperError, KeyError, ValueError, json.JSONDecodeError, OSError) as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
