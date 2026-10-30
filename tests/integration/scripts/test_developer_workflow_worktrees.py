"""Contracts for parallel worktree fleet diagnostics and fail-closed base reconciliation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.automation import developer_workflow_worktrees as worktrees

WORKFLOW_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "automation" / "developer-workflow.py"
)


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(  # noqa: S603 - fixed Git arguments against a temporary repository.
        ["git", *arguments],  # noqa: S607 - Git is the fixed test executable.
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet", "--initial-branch=main")
    _git(root, "config", "user.name", "Example User")
    _git(root, "config", "user.email", "user@example.com")
    routes_dir = root / "scripts" / "lib"
    routes_dir.mkdir(parents=True)
    (routes_dir / "design-routes.json").write_text(
        json.dumps(
            {
                "version": 1,
                "routes": [
                    {
                        "id": "baseline-no-docs",
                        "paths": ["**"],
                        "must_read": [".github/copilot-instructions.md"],
                        "validate": [],
                    },
                    {
                        "id": "shared-hotspot",
                        "paths": ["services/alpha/**", "services/beta/**"],
                        "must_read": [".github/copilot-instructions.md"],
                        "docs_update": ["docs/roadmap/architecture/project-structure.md"],
                        "validate": [],
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Example\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "initial")
    return root


def test_worktrees_diagnostic_detects_drift_reclaimable_and_hotspot_collisions(
    repo: Path,
    tmp_path: Path,
) -> None:
    wt_a = tmp_path / "wt-a"
    wt_b = tmp_path / "wt-b"
    wt_merged = tmp_path / "wt-merged"
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    wt_scratch = common / "fdai-local-validation" / "worktree"
    wt_scratch.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "--quiet", "-b", "feat/a", str(wt_a), "main")
    _git(repo, "worktree", "add", "--quiet", "-b", "feat/b", str(wt_b), "main")
    _git(repo, "worktree", "add", "--quiet", "-b", "feat/merged", str(wt_merged), "main")
    _git(repo, "worktree", "add", "--quiet", "--detach", str(wt_scratch), "main")

    # Advance main so active worktrees become behind.
    (repo / "README.md").write_text("# Example\n\nUpdated main.\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "--quiet", "-m", "advance main")
    _git(wt_merged, "merge", "--ff-only", "--quiet", "main")

    # Both wt_a and wt_b touch the same shared file and trigger the same docs_update hotspot.
    for wt, service in ((wt_a, "alpha"), (wt_b, "beta")):
        svc_dir = wt / "services" / service
        svc_dir.mkdir(parents=True)
        (svc_dir / "mod.py").write_text(f"name = '{service}'\n", encoding="utf-8")
        (wt / "shared.txt").write_text(f"from {service}\n", encoding="utf-8")
        _git(wt, "add", ".")
        _git(wt, "commit", "--quiet", "-m", f"work in {service}")

    report = worktrees.worktrees_diagnostic(repo, base_ref="refs/heads/main")

    assert report["read_only"] is True
    assert report["status"] == "warning"
    assert report["worktree_count"] == 4
    assert report["active_worktree_count"] == 2
    assert report["reclaimable_count"] == 1
    assert report["behind_active_count"] == 2
    assert report["path_collision_count"] == 1
    assert report["path_collisions"][0]["path"] == "shared.txt"
    assert report["hotspot_doc_collision_count"] == 1
    assert (
        report["hotspot_doc_collisions"][0]["document"]
        == "docs/roadmap/architecture/project-structure.md"
    )

    cli = subprocess.run(  # noqa: S603 - fixed repository script with test-owned arguments.
        [sys.executable, str(WORKFLOW_SCRIPT), "worktrees", "--base", "refs/heads/main", "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout)["hotspot_doc_collision_count"] == 1


def test_sync_worktree_fast_forwards_and_reports_up_to_date(
    repo: Path,
    tmp_path: Path,
) -> None:
    wt = tmp_path / "wt-ff"
    _git(repo, "worktree", "add", "--quiet", "-b", "feat/ff", str(wt), "main")
    assert worktrees.sync_worktree_base(wt, base_ref="refs/heads/main")["outcome"] == "up_to_date"
    (repo / "README.md").write_text("# Updated\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "--quiet", "-m", "main move")

    res = worktrees.sync_worktree_base(wt, base_ref="refs/heads/main")
    assert res["status"] == "ok"
    assert res["outcome"] == "fast_forwarded"
    assert res["head"] == _git(repo, "rev-parse", "HEAD")


def _write_doc_pair(
    root: Path,
    rel_en: str,
    en_body: str,
    ko_body: str,
    *,
    revised: str = "2026-10-30",
    override_sha: str | None = None,
) -> None:
    en_path = root / rel_en
    en_path.parent.mkdir(parents=True, exist_ok=True)
    en_path.write_text(en_body, encoding="utf-8")
    sha = override_sha or _git(root, "hash-object", rel_en)
    rel_ko = f"{rel_en.removesuffix('.md')}-ko.md"
    ko_path = root / rel_ko
    ko_path.write_text(
        f"---\ntranslation_of: {en_path.name}\n"
        f"translation_source_sha: {sha}\n"
        f"translation_revised: {revised}\n---\n\n{ko_body}",
        encoding="utf-8",
    )


def test_sync_worktree_reconciles_ko_front_matter_conflict_and_refreshes_merged_sha(
    repo: Path,
    tmp_path: Path,
) -> None:
    base_en = "# Guide\n\n## Section A\n\nOriginal A.\n\n\n\n## Section B\n\nOriginal B.\n"
    base_ko = "# 가이드\n\n## 섹션 A\n\n원본 A.\n\n\n\n## 섹션 B\n\n원본 B.\n"
    _write_doc_pair(repo, "docs/guide.md", base_en, base_ko, revised="2026-10-20")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "add guide pair")

    wt = tmp_path / "wt-ko"
    _git(repo, "worktree", "add", "--quiet", "-b", "feat/ko", str(wt), "main")

    # Main updates Section A and refreshes translation_source_sha.
    _write_doc_pair(
        repo,
        "docs/guide.md",
        base_en.replace("Original A.", "Updated A on main."),
        base_ko.replace("원본 A.", "메인 수정 A."),
        revised="2026-10-30",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "main section A")

    # Worktree updates Section B and refreshes translation_source_sha.
    _write_doc_pair(
        wt,
        "docs/guide.md",
        base_en.replace("Original B.", "Updated B on branch."),
        base_ko.replace("원본 B.", "브랜치 수정 B."),
        revised="2026-10-31",
    )
    _git(wt, "add", ".")
    _git(wt, "commit", "--quiet", "-m", "branch section B")

    result = worktrees.sync_worktree_base(wt, base_ref="refs/heads/main", today="2026-10-31")

    assert result["status"] == "ok"
    assert result["outcome"] == "reconciled_merge"
    assert result["reconciled_paths"] == ["docs/guide-ko.md"]
    merged_en_sha = _git(wt, "hash-object", "docs/guide.md")
    merged_ko = (wt / "docs/guide-ko.md").read_text(encoding="utf-8")
    assert f"translation_source_sha: {merged_en_sha}" in merged_ko
    assert "메인 수정 A." in merged_ko
    assert "브랜치 수정 B." in merged_ko


def test_sync_worktree_refuses_ko_reconciliation_when_branch_translation_was_stale(
    repo: Path,
    tmp_path: Path,
) -> None:
    base_en = "# Guide\n\n## Section A\n\nOriginal A.\n\n\n\n## Section B\n\nOriginal B.\n"
    base_ko = "# 가이드\n\n## 섹션 A\n\n원본 A.\n\n\n\n## 섹션 B\n\n원본 B.\n"
    _write_doc_pair(repo, "docs/guide.md", base_en, base_ko)
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "add guide pair")

    wt = tmp_path / "wt-stale-ko"
    _git(repo, "worktree", "add", "--quiet", "-b", "feat/stale-ko", str(wt), "main")

    _write_doc_pair(
        repo,
        "docs/guide.md",
        base_en.replace("Original A.", "Updated A on main."),
        base_ko.replace("원본 A.", "메인 수정 A."),
        revised="2026-10-30",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "main section A")

    # Branch has a bogus translation_source_sha (stale translation before merge).
    _write_doc_pair(
        wt,
        "docs/guide.md",
        base_en.replace("Original B.", "Updated B on branch."),
        base_ko,
        revised="2026-10-31",
        override_sha="0" * 40,
    )
    _git(wt, "add", ".")
    _git(wt, "commit", "--quiet", "-m", "branch stale ko")

    result = worktrees.sync_worktree_base(wt, base_ref="refs/heads/main")
    assert result["status"] == "blocked"
    assert result["reason_code"] == "unresolved_merge_conflict"
    assert _git(wt, "status", "--porcelain") == ""


def test_sync_worktree_reconciles_append_only_ledger_rows_and_blocks_same_area_conflict(
    repo: Path,
    tmp_path: Path,
) -> None:
    ledger_rel = "docs/roadmap-implementation/deployment/example.md"
    ledger_path = repo / ledger_rel
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    base_ledger = (
        "# Example ledger\n\n"
        "## Implementation status\n\n"
        "### Implementation scope\n\n"
        "| Area | State | Evidence | Notes |\n"
        "|------|-------|----------|-------|\n"
        "| Base area | implemented | `base.py` | Initial. |\n\n"
        "### Implementation history\n\n"
        "| Date | State | Change | Evidence | Remaining |\n"
        "|------|-------|--------|----------|-----------|\n"
        "| 2026-10-01 | implemented | Initial baseline. | `base.py` | None. |\n\n"
        "### Remaining work\n\n"
        "- [x] Baseline complete (`base.py`).\n"
    )
    ledger_path.write_text(base_ledger, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "add ledger")

    wt = tmp_path / "wt-ledger"
    _git(repo, "worktree", "add", "--quiet", "-b", "feat/ledger", str(wt), "main")

    # Main appends Area A and a history row.
    ledger_path.write_text(
        base_ledger.replace(
            "| Base area | implemented | `base.py` | Initial. |",
            "| Base area | implemented | `base.py` | Initial. |\n"
            "| Area A | implemented | `a.py` | Main addition. |",
        ).replace(
            "| 2026-10-01 | implemented | Initial baseline. | `base.py` | None. |",
            "| 2026-10-30 | implemented | Added Area A. | `a.py` | None. |\n"
            "| 2026-10-01 | implemented | Initial baseline. | `base.py` | None. |",
        ),
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "main ledger update")

    # Worktree appends Area B and a distinct history row at the exact same anchor lines.
    (wt / ledger_rel).write_text(
        base_ledger.replace(
            "| Base area | implemented | `base.py` | Initial. |",
            "| Base area | implemented | `base.py` | Initial. |\n"
            "| Area B | implemented | `b.py` | Branch addition. |",
        ).replace(
            "| 2026-10-01 | implemented | Initial baseline. | `base.py` | None. |",
            "| 2026-10-31 | implemented | Added Area B. | `b.py` | None. |\n"
            "| 2026-10-01 | implemented | Initial baseline. | `base.py` | None. |",
        ),
        encoding="utf-8",
    )
    _git(wt, "add", ".")
    _git(wt, "commit", "--quiet", "-m", "branch ledger update")

    result = worktrees.sync_worktree_base(wt, base_ref="refs/heads/main")
    assert result["status"] == "ok"
    assert result["outcome"] == "reconciled_merge"
    merged_text = (wt / ledger_rel).read_text(encoding="utf-8")
    assert "| Area A |" in merged_text
    assert "| Area B |" in merged_text
    assert "Added Area A." in merged_text
    assert "Added Area B." in merged_text

    # Now verify a conflicting same-Area scope row fails closed and aborts cleanly.
    wt_conflict = tmp_path / "wt-ledger-conflict"
    _git(
        repo,
        "worktree",
        "add",
        "--quiet",
        "-b",
        "feat/ledger-conflict",
        str(wt_conflict),
        "HEAD~1",
    )
    (wt_conflict / ledger_rel).write_text(
        base_ledger.replace(
            "| Base area | implemented | `base.py` | Initial. |",
            "| Base area | implemented | `base.py` | Initial. |\n"
            "| Area A | in-progress | `other.py` | Conflicting state for Area A. |",
        ),
        encoding="utf-8",
    )
    _git(wt_conflict, "add", ".")
    _git(wt_conflict, "commit", "--quiet", "-m", "conflicting Area A")

    blocked = worktrees.sync_worktree_base(wt_conflict, base_ref="refs/heads/main")
    assert blocked["status"] == "blocked"
    assert blocked["reason_code"] == "unresolved_merge_conflict"
    assert _git(wt_conflict, "status", "--porcelain") == ""


def test_sync_worktree_reconciles_additive_service_suites_conflict(
    repo: Path,
    tmp_path: Path,
) -> None:
    suites_path = repo / "tests" / "integration" / "service-suites.json"
    suites_path.parent.mkdir(parents=True, exist_ok=True)
    base_suites = {
        "schema_version": 1,
        "services": [
            {
                "id": "operator-service",
                "source_roots": ["services/operator-service"],
                "test_groups": {
                    "unit": ["services/operator-service/tests/test_base.py"],
                    "contract": [],
                    "integration": [],
                    "smoke": [],
                },
            }
        ],
    }
    suites_path.write_text(json.dumps(base_suites, indent=2) + "\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "add service suites")

    wt = tmp_path / "wt-suites"
    _git(repo, "worktree", "add", "--quiet", "-b", "feat/suites", str(wt), "main")

    main_suites = json.loads(json.dumps(base_suites))
    main_suites["services"][0]["test_groups"]["unit"].append(
        "services/operator-service/tests/test_main_added.py"
    )
    suites_path.write_text(json.dumps(main_suites, indent=2) + "\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "main suite addition")

    branch_suites = json.loads(json.dumps(base_suites))
    branch_suites["services"][0]["test_groups"]["unit"].append(
        "services/operator-service/tests/test_branch_added.py"
    )
    (wt / "tests/integration/service-suites.json").write_text(
        json.dumps(branch_suites, indent=2) + "\n",
        encoding="utf-8",
    )
    _git(wt, "add", ".")
    _git(wt, "commit", "--quiet", "-m", "branch suite addition")

    result = worktrees.sync_worktree_base(wt, base_ref="refs/heads/main")
    assert result["status"] == "ok"
    assert result["outcome"] == "reconciled_merge"
    merged = json.loads((wt / "tests/integration/service-suites.json").read_text(encoding="utf-8"))
    assert merged["services"][0]["test_groups"]["unit"] == [
        "services/operator-service/tests/test_base.py",
        "services/operator-service/tests/test_branch_added.py",
        "services/operator-service/tests/test_main_added.py",
    ]


def test_sync_worktree_clean_merge_refreshes_ko_sha_when_english_doc_merges_cleanly(
    repo: Path,
    tmp_path: Path,
) -> None:
    base_en = "# Guide\n\nSection 1.\n\n\n\n\n\nSection 2.\n"
    base_ko = "# 가이드\n\n섹션 1.\n\n\n\n\n\n섹션 2.\n"
    _write_doc_pair(repo, "docs/clean.md", base_en, base_ko, revised="2026-10-20")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "add clean pair")

    wt = tmp_path / "wt-clean-ko"
    _git(repo, "worktree", "add", "--quiet", "-b", "feat/clean-ko", str(wt), "main")

    # Main changes Section 1; worktree changes an unrelated file for a clean merge.
    _write_doc_pair(
        repo,
        "docs/clean.md",
        base_en.replace("Section 1.", "Section 1 updated."),
        base_ko.replace("섹션 1.", "섹션 1 수정."),
        revised="2026-10-20",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "main clean update")

    # Worktree changes an unrelated file so merge is clean, and we also test clean merge outcome.
    (wt / "unrelated.txt").write_text("branch change\n", encoding="utf-8")
    _git(wt, "add", "unrelated.txt")
    _git(wt, "commit", "--quiet", "-m", "branch unrelated")

    res = worktrees.sync_worktree_base(wt, base_ref="refs/heads/main", today="2026-10-31")
    assert res["status"] == "ok"
    assert res["outcome"] == "merged"
    assert res["reconciled_paths"] == []


def test_sync_worktree_guards_and_cli_modes(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.automation import parallel_worktree_reconcile as reconcile

    non_repo = tmp_path / "non-repo"
    non_repo.mkdir()
    assert worktrees.worktrees_diagnostic(non_repo)["status"] == "unavailable"
    assert worktrees.worktrees_diagnostic(repo, base_ref="refs/heads/missing")["status"] == (
        "unavailable"
    )
    assert reconcile.sync_worktree_base(non_repo)["reason_code"] == "git_repository_unavailable"
    assert (
        reconcile.sync_worktree_base(repo, base_ref="refs/heads/missing")["reason_code"]
        == "base_ref_unavailable"
    )

    # Scratch worktrees under fdai-local-validation and .fdai/local-validation-* are skipped.
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    assert worktrees._is_internal_scratch_worktree(
        common / "fdai-local-validation" / "worktree", common
    )
    assert worktrees._is_internal_scratch_worktree(
        repo / ".fdai" / "local-validation-1234" / "worktree", common
    )

    # Detached HEAD and dirty tree guards.
    wt_guard = tmp_path / "wt-guard"
    _git(repo, "worktree", "add", "--quiet", "--detach", str(wt_guard), "main")
    assert reconcile.sync_worktree_base(wt_guard)["reason_code"] == "detached_head"
    _git(wt_guard, "checkout", "--quiet", "-b", "feat/guard")
    (wt_guard / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    assert reconcile.sync_worktree_base(wt_guard)["reason_code"] == "worktree_dirty"
    (wt_guard / "dirty.txt").unlink()

    # In-progress merge guard.
    wt_git_dir = Path(_git(wt_guard, "rev-parse", "--path-format=absolute", "--git-dir"))
    (wt_git_dir / "MERGE_HEAD").write_text("0" * 40 + "\n", encoding="utf-8")
    assert reconcile.sync_worktree_base(wt_guard)["reason_code"] == "git_operation_in_progress"
    (wt_git_dir / "MERGE_HEAD").unlink()

    # Fetch failure and timeout guards.
    assert (
        reconcile.sync_worktree_base(wt_guard, base_ref="refs/remotes/origin/main", fetch=True)[
            "reason_code"
        ]
        == "base_fetch_failed"
    )

    real_run = subprocess.run

    def raise_fetch_timeout(
        command: list[str], *args: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["git", "fetch"]:
            raise subprocess.TimeoutExpired(cmd=command, timeout=60)
        return real_run(command, *args, **kwargs)  # type: ignore[return-value]

    monkeypatch.setattr(reconcile.subprocess, "run", raise_fetch_timeout)
    assert (
        reconcile.sync_worktree_base(wt_guard, base_ref="refs/remotes/origin/main", fetch=True)[
            "reason_code"
        ]
        == "base_fetch_timeout"
    )
    monkeypatch.setattr(reconcile.subprocess, "run", real_run)

    # Symlink escape guard.
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (wt_guard / "link.txt").symlink_to(outside)
    assert reconcile._safe_worktree_file(wt_guard, "link.txt") is None
    (wt_guard / "link.txt").unlink()

    # CLI entry points.
    monkeypatch.chdir(wt_guard)
    assert worktrees.main(["status", "--base", "refs/heads/main"]) == 0
    assert "worktrees: status=" in capsys.readouterr().out
    assert worktrees.main(["status", "--base", "refs/heads/main", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] in {"ok", "warning"}
    assert worktrees.main(["sync", "--base", "refs/heads/main"]) == 0
    assert "sync-worktree: status=ok" in capsys.readouterr().out
    assert worktrees.main(["sync", "--base", "refs/heads/main", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "up_to_date"
    assert worktrees.main(["sync", "--base", "refs/heads/missing"]) == 1
    assert "sync-worktree: BLOCKED" in capsys.readouterr().err

    # Also test developer-workflow.py worktrees text output.
    text_cli = subprocess.run(  # noqa: S603 - fixed repository script with test-owned arguments.
        [sys.executable, str(WORKFLOW_SCRIPT), "worktrees", "--base", "refs/heads/main"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert text_cli.returncode == 0
    assert "developer-workflow: worktrees" in text_cli.stdout


def test_reconciler_fail_closed_edge_cases(
    repo: Path,
    tmp_path: Path,
) -> None:
    from scripts.automation import parallel_worktree_reconcile as reconcile

    # 1. _docs_update_targets handles empty changed_paths and missing/invalid design-routes.json.
    assert worktrees._docs_update_targets(tmp_path, []) == []
    assert worktrees._docs_update_targets(tmp_path, ["a.py"]) == []
    bad_routes = tmp_path / "scripts" / "lib"
    bad_routes.mkdir(parents=True)
    (bad_routes / "design-routes.json").write_text("{bad json", encoding="utf-8")
    assert worktrees._docs_update_targets(tmp_path, ["a.py"]) == []

    # 2. _reconcile_ko_conflict refuses when body has conflict markers or src is also unmerged.
    base_en = "# Guide\n\nShared line.\n"
    base_ko = "# 가이드\n\n공통 문장.\n"
    _write_doc_pair(repo, "docs/body.md", base_en, base_ko, revised="2026-10-20")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "add body doc")

    wt_body = tmp_path / "wt-body"
    _git(repo, "worktree", "add", "--quiet", "-b", "feat/body", str(wt_body), "main")

    _write_doc_pair(
        repo,
        "docs/body.md",
        "# Guide\n\nShared line.\n\nMain extra.\n",
        "# 가이드\n\n메인 문장 충돌.\n",
        revised="2026-10-30",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "main body edit")

    _write_doc_pair(
        wt_body,
        "docs/body.md",
        "# Guide\n\nBranch header.\n\nShared line.\n",
        "# 가이드\n\n브랜치 문장 충돌.\n",
        revised="2026-10-31",
    )
    _git(wt_body, "add", ".")
    _git(wt_body, "commit", "--quiet", "-m", "branch body edit")

    body_res = reconcile.sync_worktree_base(wt_body, base_ref="refs/heads/main")
    assert body_res["status"] == "blocked"
    assert body_res["reason_code"] == "unresolved_merge_conflict"

    # 3. _reconcile_table_hunks refuses non-table lines, separator-only lines, and wrong arity.
    assert (
        reconcile._reconcile_table_hunks(
            "<<<<<<< HEAD\nnot a table row\n=======\n| a | b | c | d |\n>>>>>>> main\n",
            expected_columns=4,
            unique_first_col=True,
        )
        is None
    )
    assert reconcile._table_row_cells("| --- | --- |") is None

    # 4. _reconcile_ledger_conflict refuses conflicts in Remaining work or invalid states.
    ledger_rel = "docs/roadmap-implementation/deployment/bad.md"
    bad_ledger = repo / ledger_rel
    bad_ledger.parent.mkdir(parents=True, exist_ok=True)
    bad_ledger.write_text(
        "# Bad\n\n## Implementation status\n\n### Implementation scope\n\n"
        "| Area | State | Evidence | Notes |\n|------|-------|----------|-------|\n"
        "| A | implemented | `a.py` | ok |\n\n### Implementation history\n\n"
        "| Date | State | Change | Evidence | Remaining |\n"
        "|------|-------|--------|----------|-----------|\n"
        "| 2026-10-01 | implemented | init | `a.py` | none |\n\n### Remaining work\n\n"
        "<<<<<<< HEAD\n- [ ] Task A\n=======\n- [ ] Task B\n>>>>>>> main\n",
        encoding="utf-8",
    )
    head_sha = _git(repo, "rev-parse", "HEAD")
    assert not reconcile._reconcile_ledger_conflict(
        repo, ledger_rel, head_sha=head_sha, base_sha=head_sha
    )
    bad_ledger.write_text("# Missing headings\n", encoding="utf-8")
    assert not reconcile._reconcile_ledger_conflict(
        repo, ledger_rel, head_sha=head_sha, base_sha=head_sha
    )
    bad_ledger.unlink()
    assert not reconcile._reconcile_ko_conflict(
        repo,
        "docs/body-ko.md",
        head_sha=head_sha,
        base_sha=head_sha,
        unmerged={"docs/body.md", "docs/body-ko.md"},
        stamp="2026-10-31",
    )

    # 5. _reconcile_service_suites_conflict refuses non-additive edits.
    suites_rel = "tests/integration/service-suites.json"
    suites_file = repo / suites_rel
    suites_file.parent.mkdir(parents=True, exist_ok=True)
    suites_file.write_text('{"schema_version": 1, "services": []}\n', encoding="utf-8")
    _git(repo, "add", suites_rel)
    _git(repo, "commit", "--quiet", "-m", "empty suites")
    empty_sha = _git(repo, "rev-parse", "HEAD")
    assert not reconcile._reconcile_service_suites_conflict(
        repo, merge_base=empty_sha, head_sha=empty_sha, base_sha=empty_sha
    )
