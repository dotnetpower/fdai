"""Tests for local-folder acquisition, ref resolution, scan targets, and scan reports."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import pytest
from fdai.core.security.code_findings import (
    AnalysisContext,
    Lane,
    SarifIngestContext,
    build_issues,
    ingest_sarif,
)
from fdai.core.security.code_findings.receipts import build_receipt
from fdai.core.security.code_findings.review_signal import ReviewSource, build_review_package
from fdai.delivery.code_security_acquire import GitSourceAcquirer, SourceAcquisitionError
from fdai.delivery.code_security_report import (
    _redacted_secret_line,
    render_html,
    render_markdown,
    render_sarif,
    scan_report_document,
    write_scan_report,
)
from fdai.delivery.code_security_sandbox import BubblewrapScannerSandbox, sandbox_available
from fdai.delivery.code_security_scan_cli import derive_alias, scan_target
from fdai.delivery.code_security_scan_job import ScanJobConfig, ScanJobResult, run_scan_job
from fdai.rule_catalog.code_security import Exposure, load_code_security_catalog
from fdai.rule_catalog.code_security_scanners import ScannerCatalog, load_scanner_catalog

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CATALOG = _REPO_ROOT / "rule-catalog" / "code-security"
_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Example Dev",
    "GIT_AUTHOR_EMAIL": "dev@example.com",
    "GIT_COMMITTER_NAME": "Example Dev",
    "GIT_COMMITTER_EMAIL": "dev@example.com",
}
needs_bwrap = pytest.mark.skipif(
    not sandbox_available(), reason="unprivileged bubblewrap unavailable"
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - controlled test command
        ["git", "-C", str(cwd), *args],  # noqa: S607 - git from PATH in tests
        check=True,
        capture_output=True,
        text=True,
        env=_ENV,
    ).stdout.strip()


def _plain_repo(tmp_path: Path) -> tuple[Path, str]:
    """A repository without uploadpack overrides, like a developer's checkout."""
    repo = tmp_path / "checkout"
    (repo / "src").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    (repo / ".gitignore").write_text("build/\n")
    (repo / "src" / "app.py").write_text("import os\nos.system(cmd)\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    _git(repo, "tag", "-a", "v1", "-m", "release")
    return repo, _git(repo, "rev-parse", "HEAD")


def _sarif(driver: str = "Opengrep", path: str = "src/app.py") -> str:
    return json.dumps(
        {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": driver, "version": "1.0.0"}},
                    "results": [
                        {
                            "ruleId": "fdai.python.os-system",
                            "properties": {"tags": ["CWE-78"]},
                            "message": {"text": "os.system with SECRET_TOKEN=abc"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": f"file:///source/{path}"},
                                        "region": {"startLine": 2},
                                    }
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )


def test_local_git_folder_scans_its_committed_head(tmp_path: Path) -> None:
    repo, head = _plain_repo(tmp_path)
    (repo / "src" / "draft.py").write_text("eval(x)\n")
    source = GitSourceAcquirer(tmp_path / "work").acquire_path(repo)
    assert (source.revision, source.revision_kind) == (head, "commit")
    assert (source.path / "src" / "app.py").exists()
    assert not (source.path / "src" / "draft.py").exists()


def test_uncommitted_snapshot_includes_untracked_but_not_ignored_files(tmp_path: Path) -> None:
    repo, head = _plain_repo(tmp_path)
    (repo / "src" / "draft.py").write_text("eval(x)\n")
    (repo / "build").mkdir()
    (repo / "build" / "out.py").write_text("ignored\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("not part of the folder\n")
    (repo / "src" / "link.txt").symlink_to(outside)
    acquirer = GitSourceAcquirer(tmp_path / "work")
    source = acquirer.acquire_path(repo, include_uncommitted=True)
    assert source.revision_kind == "snapshot" and source.revision != head
    assert len(source.revision) == 64
    assert (source.path / "src" / "draft.py").exists()
    assert not (source.path / "build").exists()
    assert not (source.path / "src" / "link.txt").exists()
    assert not os.access(source.path / "src" / "app.py", os.W_OK)
    assert acquirer.acquire_path(repo, include_uncommitted=True).revision == source.revision
    (repo / "src" / "draft.py").write_text("eval(y)\n")
    assert acquirer.acquire_path(repo, include_uncommitted=True).revision != source.revision


def test_folder_outside_git_is_snapshotted_and_empty_folder_fails(tmp_path: Path) -> None:
    folder = tmp_path / "plain"
    (folder / ".git").mkdir(parents=True)
    (folder / ".git" / "config").write_text("not a real repository\n")
    (folder / "main.go").write_text("package main\n")
    acquirer = GitSourceAcquirer(tmp_path / "work")
    source = acquirer.acquire_path(folder)
    assert source.revision_kind == "snapshot"
    assert sorted(p.name for p in source.path.iterdir()) == ["main.go"]
    (tmp_path / "empty").mkdir()
    with pytest.raises(SourceAcquisitionError, match="no files"):
        acquirer.acquire_path(tmp_path / "empty")
    with pytest.raises(SourceAcquisitionError, match="existing directory"):
        acquirer.acquire_path(tmp_path / "missing")


def test_repository_subfolder_needs_the_root_or_a_snapshot(tmp_path: Path) -> None:
    repo, _ = _plain_repo(tmp_path)
    acquirer = GitSourceAcquirer(tmp_path / "work")
    with pytest.raises(SourceAcquisitionError, match="repository root"):
        acquirer.acquire_path(repo / "src")
    source = acquirer.acquire_path(repo / "src", include_uncommitted=True)
    assert sorted(p.name for p in source.path.iterdir()) == ["app.py"]


def test_resolve_revision_accepts_branches_tags_and_commits(tmp_path: Path) -> None:
    repo, head = _plain_repo(tmp_path)
    acquirer = GitSourceAcquirer(tmp_path / "work")
    assert acquirer.resolve_revision(str(repo), "main") == head
    assert acquirer.resolve_revision(str(repo), "v1") == head
    assert acquirer.resolve_revision(str(repo), "HEAD") == head
    assert acquirer.resolve_revision(str(repo), "f" * 40) == "f" * 40
    with pytest.raises(SourceAcquisitionError, match="exactly one commit"):
        acquirer.resolve_revision(str(repo), "missing-branch")
    for bad in ("../main", "-x", "a b", ""):
        with pytest.raises(SourceAcquisitionError, match="ref must be"):
            acquirer.resolve_revision(str(repo), bad)


def _args(**values: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "path": None,
        "repository": None,
        "revision": None,
        "repo_alias": None,
        "source_provider": None,
        "include_uncommitted": False,
    }
    defaults.update(values)
    return argparse.Namespace(**defaults)


def test_scan_target_validates_and_labels_the_source(tmp_path: Path) -> None:
    folder = tmp_path / "My Service!"
    folder.mkdir()
    alias, source = scan_target(_args(path=str(folder)))
    assert alias == "My-Service" and source.kind == "local_path" and source.provider == "local"
    alias, source = scan_target(
        _args(repository="https://github.com/example/app.git", revision="main", repo_alias="app")
    )
    assert (alias, source.kind, source.provider) == ("app", "git_repository", "github")
    for bad in (
        _args(path=str(folder), repository="x"),
        _args(include_uncommitted=True, repository="x", revision="main", repo_alias="a"),
        _args(repository="x"),
    ):
        with pytest.raises(ValueError):
            scan_target(bad)
    assert derive_alias(tmp_path / "...") == "local-folder"


def _result(tmp_path: Path, *, revision_kind: str = "commit") -> ScanJobResult:
    revision = "a" * 40
    catalog = load_code_security_catalog(_CATALOG)
    ingested = [
        ingest_sarif(
            _sarif().encode(),
            SarifIngestContext(
                lane=Lane.DETERMINISTIC,
                revision=revision,
                producer="Opengrep",
                source_roots=("/source",),
            ),
        )
    ]
    issues = build_issues(
        [occ for item in ingested for occ in item.occurrences],
        catalog,
        AnalysisContext(revision=revision),
    )
    receipt = build_receipt(revision, catalog.version_stamp(), ingested)
    package = build_review_package(
        issues,
        repository_alias="example-service",
        revision=revision,
        exposure=Exposure.UNKNOWN,
        coverage_complete=False,
        source=ReviewSource(kind="local_path", provider="local", revision_kind=revision_kind),
        producers=["Opengrep"],
    )
    sarif_file = tmp_path / "opengrep.sarif"
    source_file = tmp_path / "src" / "app.py"
    source_file.parent.mkdir(exist_ok=True)
    source_file.write_text("def run(cmd):\n    os.system(cmd)\n")
    return ScanJobResult(
        revision=revision,
        tree_id="t",
        issues=issues,
        receipt=receipt,
        package=package,
        runs=(),
        coverage_limits=("required scanner gitleaks is not installed",),
        published=False,
        artifact_dir=tmp_path,
        sarif_files=(sarif_file,),
        revision_kind=revision_kind,
        source_path=tmp_path,
    )


def test_report_lists_issues_without_code_or_scanner_text(tmp_path: Path) -> None:
    result = _result(tmp_path)
    paths = write_scan_report(
        result,
        tmp_path / "report",
        repository_alias="example-service",
        source_label="local_path:local",
        generated_at="2026-10-08T00:00:00+00:00",
    )
    markdown = paths.markdown.read_text()
    page = paths.html.read_text()
    document = json.loads(paths.json.read_text())
    assert document["decision"] == "coverage_incomplete"
    (issue,) = document["issues"]
    assert issue["weakness_class"] == "command_injection" and issue["cwe"] == ["CWE-78"]
    assert issue["location"] == "src/app.py:2"
    assert "| src/app.py:2 |" in markdown
    assert "**Decision:** coverage incomplete" in markdown
    assert issue["identifiers"] == ["CWE-78"]
    assert "| CWE-78 | src/app.py:2 | Opengrep | no |" in markdown
    assert "SECRET_TOKEN" not in markdown + page + paths.json.read_text()
    assert "os.system(cmd)" not in markdown + page
    assert "fdai-code-security export --revision" in markdown
    assert "Content-Security-Policy" in page and "<script" not in page
    assert oct(paths.html.stat().st_mode & 0o777) == "0o600"
    sarif = json.loads(
        render_sarif(
            result,
            repository_alias="example-service",
            generated_at="2026-10-08T00:00:00+00:00",
        )
    )
    sarif_result = sarif["runs"][0]["results"][0]
    assert sarif["version"] == "2.1.0"
    assert sarif_result["properties"]["issue_id"] == issue["issue_id"]
    assert sarif_result["properties"]["title"]
    assert sarif_result["properties"]["severity_floor"] in {"low", "medium", "high", "critical"}
    assert sarif_result["properties"]["severity_ceiling"] in {"low", "medium", "high", "critical"}
    assert isinstance(sarif_result["properties"]["deciding_facts"], list)
    assert sarif_result["properties"]["code_context"]["highlight_start"] == 2
    assert sarif_result["properties"]["code_context"]["lines"][1]["text"] == "    os.system(cmd)"
    assert sarif_result["properties"]["flow_steps"][-1] == {
        "kind": "sink",
        "path": "src/app.py",
        "line": 2,
    }
    assert (
        sarif_result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "src/app.py"
    )
    assert "scanner said" not in json.dumps(sarif)


def test_report_escapes_html_and_localizes_to_korean(tmp_path: Path) -> None:
    document = scan_report_document(
        _result(tmp_path, revision_kind="snapshot"),
        repository_alias="<b>x</b>",
        source_label="local_path:local",
        generated_at="2026-10-08T00:00:00+00:00",
    )
    page = render_html(document, "ko")
    assert "<b>x</b>" not in page and "&lt;b&gt;x&lt;/b&gt;" in page
    assert '<html lang="ko">' in page and "코드 보안 스캔 보고서" in page
    document["scanners"] = [{"scanner": "opengrep", "completed": True, "exit_code": 0}]
    markdown = render_markdown(document, "ko")
    assert "| opengrep | 예 | 0 |" in markdown and "True" not in markdown
    assert "커밋하지 않은 스냅샷" in markdown
    assert "fdai-code-security export" not in markdown
    issues = document["issues"]
    assert isinstance(issues, list)
    issues[0]["location"] = "src/a|b`c.py:2"
    assert "src/a\\|b'c.py:2" in render_markdown(document)


def test_secret_context_redacts_the_value_but_keeps_the_assignment_key() -> None:
    rendered = _redacted_secret_line("  connectionString: super-secret-value")
    assert rendered == '  connectionString: "<sensitive value redacted>"'
    assert "super-secret-value" not in rendered


@needs_bwrap
async def test_scan_job_scans_a_local_snapshot_and_records_its_source(tmp_path: Path) -> None:
    repo, _ = _plain_repo(tmp_path)
    (repo / "src" / "draft.py").write_text("x = 1\n")
    scanner = tmp_path / "bin" / "fake-scanner"
    scanner.parent.mkdir()
    scanner.write_text(f"#!/bin/sh\ncat <<'SARIF'\n{_sarif()}\nSARIF\n")
    scanner.chmod(0o755)
    scanners = load_scanner_catalog(_CATALOG)
    result = await run_scan_job(
        ScanJobConfig(
            repository="",
            revision="",
            repository_alias="example-service",
            work_root=tmp_path / "work",
            executables={"opengrep": scanner},
            rules_dir=_CATALOG / "rules",
            required_scanners=frozenset({"opengrep"}),
            local_path=repo,
            include_uncommitted=True,
            source=ReviewSource(kind="local_path", provider="local"),
        ),
        catalog=load_code_security_catalog(_CATALOG),
        scanners=ScannerCatalog(
            schema_version=1,
            catalog_id="test-catalog",
            version="1.0.0",
            scanners={"opengrep": scanners.scanners["opengrep"]},
        ),
        acquirer=GitSourceAcquirer(tmp_path / "work"),
        sandbox=BubblewrapScannerSandbox(),
    )
    assert result.revision_kind == "snapshot"
    assert result.package["source"] == {
        "kind": "local_path",
        "provider": "local",
        "revision_kind": "snapshot",
        "trigger": "cli",
        "request_id": None,
    }
    assert result.package["producers"] == ["Opengrep"]
    assert result.package["revision"] == result.revision
