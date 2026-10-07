"""Shared runtime for the FDAI remediation-pack helper (standard library only).

This module holds the pack reader, ledger persistence, git invocation, scope selection, and the
read-only commands (``verify``, ``summary``, ``plan``, ``next-group``) used by ``pack_helper.py``.
It ships in every remediation pack as ``tools/fdai_pack_runtime.py`` and must import only the
Python standard library.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

HELPER_VERSION = "1.0.0"
LEDGER = "ledger/remediation-ledger.json"
RESULT = "result/remediation-result.json"
ISSUE_STATUSES = (
    "fixed_claimed",
    "mitigated_claimed",
    "claimed_false_positive",
    "stale_or_already_fixed",
    "deferred",
    "failed",
    "plan_only",
    "not_attempted",
)
VALIDATIONS = ("tests_passed", "tests_failed", "manual_validation_required", "not_run")
SCOPE_CHOICES: dict[str, tuple[str, ...]] = {
    "targets": ("p0-p1", "severity-high", "all", "ids"),
    "confidence": ("reported", "corroborated", "verified", "hypothesis"),
    "depth": ("D2", "D0", "D1", "D3"),
    "pace": ("group", "issue", "batch"),
    "commits": ("per-group", "per-issue", "single"),
    "on_failure": ("rollback-continue", "stop"),
}
RECOMMENDED_SCOPE: dict[str, Any] = {key: values[0] for key, values in SCOPE_CHOICES.items()}
CONFIDENCE_ORDER = {"hypothesis": 1, "reported": 2, "corroborated": 3, "verified": 4, "proven": 5}
DEPTH_ORDER = {"D0": 0, "D1": 1, "D2": 2, "D3": 3}
BAND_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
ID_PATTERN = re.compile(r"^(FDAI-SEC-[0-9a-f]{12}|FG-\d{3})$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")


class HelperError(Exception):
    """A precondition failed; the message explains what to do."""


def now_utc() -> dt.datetime:
    # timezone.utc keeps the shipped helper compatible with Python 3.10.
    return dt.datetime.now(dt.timezone.utc)  # noqa: UP017


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(  # noqa: S603 - fixed git argv, no shell
        ["git", "-C", str(repo), *args],  # noqa: S607 - git is resolved from PATH by design
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise HelperError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip()[:300]}")
    return proc


def clean_text(value: object, limit: int) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f\u202a-\u202e\u2066-\u2069]", "", str(value or ""))
    return text[:limit]


class Pack:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        manifest_path = self.root / "pack.manifest.json"
        try:
            raw = manifest_path.read_bytes()
        except FileNotFoundError as exc:
            raise HelperError("pack.manifest.json not found; check --pack") from exc
        self.manifest_sha256 = hashlib.sha256(raw).hexdigest()
        self.manifest: dict[str, Any] = json.loads(raw)
        self.pack_id = str(self.manifest["pack_id"])

    def read_json(self, relative: str) -> dict[str, Any]:
        document = json.loads((self.root / relative).read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise HelperError(f"{relative} must contain a JSON object")
        return document

    def index(self) -> dict[str, Any]:
        return self.read_json("findings/index.json")

    def group(self, group_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"FG-\d{3}", group_id):
            raise HelperError("group id must look like FG-001")
        return self.read_json(f"findings/groups/{group_id}.json")

    def policy(self) -> dict[str, Any]:
        return self.read_json("policy/remediation-policy.json")

    def ledger(self) -> dict[str, Any]:
        path = self.root / LEDGER
        if path.exists():
            return self.read_json(LEDGER)
        return {
            "schema_version": 1,
            "pack_id": self.pack_id,
            "scope": None,
            "branch": None,
            "start_head": None,
            "session": {"started_at": None, "groups_finished": 0},
            "groups": {},
            "issues": {},
        }

    def save(self, relative: str, document: dict[str, Any]) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)


def repo_root(repo: Path) -> Path:
    return Path(git(repo, "rev-parse", "--show-toplevel").stdout.strip())


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def pack_rel(pack: Pack, top: Path) -> str | None:
    try:
        return pack.root.relative_to(top).as_posix()
    except ValueError:
        return None


def commit_ref(value: object, label: str) -> str:
    """Return ``value`` if it is a full commit id; ledger and manifest values are untrusted."""
    if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
        raise HelperError(f"{label} must be a full commit id")
    return value


def _inside(path: str, inside: str | None) -> bool:
    return bool(inside) and (path == inside or path.startswith(f"{inside}/"))


def dirty_paths(pack: Pack, repo: Path) -> list[str]:
    """Return changed or untracked paths outside the pack, read NUL-delimited and unquoted."""
    top = repo_root(repo)
    inside = pack_rel(pack, top)
    records = git(top, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout.split("\0")
    dirty: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if len(record) < 4:
            continue
        if record[0] in "RC":
            index += 1  # the next record is the rename or copy source
        if not _inside(record[3:], inside):
            dirty.append(record)
    return dirty


def untracked_paths(pack: Pack, top: Path) -> list[str]:
    """Return repository-relative untracked paths outside the pack (NUL-delimited, unquoted)."""
    inside = pack_rel(pack, top)
    output = git(top, "ls-files", "-z", "--full-name", "--others", "--exclude-standard").stdout
    return [path for path in output.split("\0") if path and not _inside(path, inside)]


def require_pack_ignored(pack: Pack, top: Path) -> None:
    """Refuse to proceed when the pack sits inside the repository without being ignored."""
    inside = pack_rel(pack, top)
    if inside and git(top, "check-ignore", "-q", inside, check=False).returncode != 0:
        raise HelperError(
            "the pack directory is inside the repository; add it to .git/info/exclude"
        )


def tampered_files(pack: Pack) -> list[str]:
    """Return pack files whose content no longer matches the manifest digest."""
    bad = []
    for entry in pack.manifest.get("files", []):
        target = (pack.root / entry["path"]).resolve()
        if pack.root not in target.parents or not target.is_file():
            bad.append(entry["path"])
        elif hashlib.sha256(target.read_bytes()).hexdigest() != entry["sha256"]:
            bad.append(entry["path"])
    return bad


def in_scope(issue: dict[str, Any], scope: dict[str, Any]) -> bool:
    targets = scope["targets"]
    if targets == "p0-p1" and issue["priority"] not in ("P0", "P1"):
        return False
    if targets == "severity-high" and BAND_ORDER[issue["severity_ceiling"]] < BAND_ORDER["high"]:
        return False
    if targets == "ids" and not (
        {issue["issue_id"], issue["group_id"]} & set(scope.get("ids", []))
    ):
        return False
    return CONFIDENCE_ORDER[issue["confidence"]] >= CONFIDENCE_ORDER[scope["confidence"]]


def require_scope(pack: Pack) -> dict[str, Any]:
    scope = pack.ledger().get("scope")
    if not isinstance(scope, dict) or not scope:
        raise HelperError("record the scope first: record scope --recommended or --json")
    return scope


def plan_groups(pack: Pack) -> list[dict[str, Any]]:
    scope = require_scope(pack)
    index = pack.index()
    selected = {issue["issue_id"] for issue in index["issues"] if in_scope(issue, scope)}
    return [group for group in index["groups"] if selected & set(group["issue_ids"])]


def cmd_verify(pack: Pack, repo: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(check_id: str, ok: bool, detail: str = "") -> None:
        checks.append({"id": check_id, "ok": ok, "detail": detail})

    add("manifest-schema", pack.manifest.get("schema_version") == 1)
    bad = tampered_files(pack)
    add("file-digests", not bad, ", ".join(bad[:10]))
    checks.append(
        {
            "id": "signature",
            "ok": True,
            "warning": (
                "pack signature is not verified locally in helper 1.0.0; "
                "FDAI verifies the manifest digest on import"
            ),
        }
    )
    expires = dt.datetime.fromisoformat(pack.manifest["expires_at"])
    add("not-expired", now_utc() <= expires, pack.manifest["expires_at"])
    top = repo_root(repo)
    base = commit_ref(pack.manifest["repository"]["base_commit"], "base_commit")
    exists = git(top, "cat-file", "-e", f"{base}^{{commit}}", check=False).returncode == 0
    add("base-commit-present", exists, base)
    ancestor = (
        exists
        and git(repo, "merge-base", "--is-ancestor", base, "HEAD", check=False).returncode == 0
    )
    add(
        "head-contains-base",
        ancestor,
        "HEAD is ahead of the base; relocate issues by fix site"
        if ancestor and head(repo) != base
        else "",
    )
    inside = pack_rel(pack, top)
    if inside is not None:
        ignored = git(repo, "check-ignore", "-q", inside, check=False).returncode == 0
        add(
            "pack-ignored",
            ignored,
            "add the pack directory to .git/info/exclude" if not ignored else "",
        )
    dirty = dirty_paths(pack, repo)
    add("clean-tree", not dirty, "; ".join(dirty[:10]))
    ledger = pack.ledger()
    if ledger.get("start_head"):
        same_pack = ledger.get("pack_id") == pack.pack_id
        branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        commits = [c for g in ledger["groups"].values() for c in g.get("commits", [])]
        last = commit_ref(commits[-1] if commits else ledger["start_head"], "ledger commit")
        contains = (
            git(repo, "merge-base", "--is-ancestor", last, "HEAD", check=False).returncode == 0
        )
        add(
            "resume-state",
            same_pack and branch == ledger.get("branch") and contains,
            f"ledger branch {ledger.get('branch')}, current {branch}",
        )
    return {"ok": all(item["ok"] for item in checks), "pack_id": pack.pack_id, "checks": checks}


def cmd_summary(pack: Pack) -> dict[str, Any]:
    index = pack.index()
    counts: dict[str, int] = {}
    for issue in index["issues"]:
        key = f"{issue['priority']}|{issue['severity']}|{issue['confidence']}"
        counts[key] = counts.get(key, 0) + 1
    rows = ["| Priority | Severity | Confidence | Issues |", "|---|---|---|---|"]
    for key in sorted(counts):
        priority, severity, confidence = key.split("|")
        rows.append(f"| {priority} | {severity} | {confidence} | {counts[key]} |")
    eligibility: dict[str, int] = {}
    for group in index["groups"]:
        eligibility[group["autofix_eligibility"]] = (
            eligibility.get(group["autofix_eligibility"], 0) + 1
        )
    return {
        "ok": True,
        "table_markdown": "\n".join(rows),
        "issues": len(index["issues"]),
        "groups": len(index["groups"]),
        "groups_by_eligibility": eligibility,
        "coverage_limits": index.get("coverage_limits", []),
        "omitted": index.get("omitted", {}),
    }


def cmd_plan(pack: Pack) -> dict[str, Any]:
    groups = plan_groups(pack)
    limit = int(pack.policy()["limits"]["max_groups_per_session"])
    return {"ok": True, "session_limit": limit, "groups": groups}


def cmd_next_group(pack: Pack) -> dict[str, Any]:
    scope = require_scope(pack)
    ledger = pack.ledger()
    limit = int(pack.policy()["limits"]["max_groups_per_session"])
    if ledger["session"]["groups_finished"] >= limit:
        return {"ok": True, "done": False, "session_limit_reached": True}
    index = {issue["issue_id"]: issue for issue in pack.index()["issues"]}
    for summary in plan_groups(pack):
        state = ledger["groups"].get(summary["group_id"], {}).get("status", "pending")
        if state in ("done", "failed", "skipped"):
            continue
        group = pack.group(summary["group_id"])
        scoped_ids = [i for i in group["issue_ids"] if in_scope(index[i], scope)]
        depth = (
            "plan_only"
            if group["max_depth"] == "plan_only"
            else min(scope["depth"], group["max_depth"], key=lambda d: DEPTH_ORDER[d])
        )
        return {
            "ok": True,
            "done": False,
            "group": group,
            "effective_depth": depth,
            "in_scope_issue_ids": scoped_ids,
            "triage_only_issue_ids": [
                i for i in scoped_ids if index[i]["confidence"] == "hypothesis"
            ],
        }
    return {"ok": True, "done": True}
