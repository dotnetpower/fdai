from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fdai_service_contracts.system_knowledge import SystemKnowledgeQueryRequest
from fdai_system_knowledge_service.catalog import (
    compile_reference_catalog,
    load_catalog,
    resolve_protected_main_revision,
)
from fdai_system_knowledge_service.search import SystemKnowledgeIndex

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = (
    REPO_ROOT
    / "services/system-knowledge-service/src/fdai_system_knowledge_service/data/catalog.json"
)


def _request(query: str, *, locale: str = "en") -> SystemKnowledgeQueryRequest:
    return SystemKnowledgeQueryRequest(
        query=query,
        locale=locale,
        principal_scope_digest="sha256:" + ("a" * 64),
    )


def _git_at(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    assert git is not None
    return subprocess.run(  # noqa: S603 - resolved git executes fixed test-owned arguments
        [git, *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return _git_at(REPO_ROOT, *arguments)


def test_packaged_catalog_matches_current_reviewed_sources() -> None:
    packaged = load_catalog(CATALOG_PATH)
    rebuilt = compile_reference_catalog(
        REPO_ROOT,
        generated_at=packaged.generated_at,
        source_revision="HEAD",
    )

    assert rebuilt.records == packaged.records
    if _git("rev-parse", "--is-shallow-repository").stdout.strip() == "false":
        _git(
            "merge-base",
            "--is-ancestor",
            packaged.source_revision,
            "refs/remotes/origin/main",
        )
        for record in packaged.records:
            for source in record.sources:
                assert _git("hash-object", source.path).stdout.strip() == source.blob_sha
    assert len(rebuilt.records) == 21


def test_protected_main_resolver_ignores_side_branch_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_at(repo, "init", "--quiet", "--initial-branch", "main")
    _git_at(repo, "config", "user.email", "tests@example.com")
    _git_at(repo, "config", "user.name", "FDAI Tests")
    (repo / "source.txt").write_text("main\n", encoding="utf-8")
    _git_at(repo, "add", "source.txt")
    _git_at(repo, "commit", "--quiet", "-m", "main")
    main_revision = _git_at(repo, "rev-parse", "HEAD").stdout.strip()
    _git_at(repo, "update-ref", "refs/remotes/origin/main", main_revision)
    _git_at(repo, "switch", "--quiet", "-c", "feature")
    (repo / "source.txt").write_text("feature\n", encoding="utf-8")
    _git_at(repo, "commit", "--quiet", "-am", "feature")

    assert resolve_protected_main_revision(repo) == main_revision


def test_exact_alias_and_korean_paraphrase_return_grounded_records() -> None:
    index = SystemKnowledgeIndex(load_catalog(CATALOG_PATH))

    exact = index.search(_request("How does FDAI keep actions safe?"))
    korean = index.search(_request("FDAI 시스템 지식 봇은 어떻게 동작하나요?", locale="ko"))
    console_sec = index.search(_request("FDAI 콘솔웹이 보안상 문제가 없나?", locale="ko"))
    iam_sec = index.search(
        _request("FDAI에서 권한이나 RBAC, Entra ID 토큰 보안은 어떻게 검증하나요?", locale="ko")
    )
    safeguard_sec = index.search(
        _request("FDAI 자율 실행의 7대 안전장치와 위험 등급 관문은 무엇인가요?", locale="ko")
    )
    audit_sec = index.search(
        _request(
            "감사 로그 위변조 방지와 Saga 해시 체인 및 DSSE 서명 검증은 어떻게 동작하나요?",
            locale="ko",
        )
    )

    assert exact.matches[0].match_kind == "exact_alias"
    assert exact.matches[0].record.knowledge_id == "action-safety"
    assert korean.matches[0].record.knowledge_id == "system-knowledge-service"
    assert console_sec.matches[0].match_kind == "exact_alias"
    assert console_sec.matches[0].record.knowledge_id == "console-web-security"
    assert iam_sec.matches[0].record.knowledge_id == "iam-rbac-and-jwt-boundary"
    assert safeguard_sec.matches[0].record.knowledge_id == "seven-safeguard-execution-boundary"
    assert audit_sec.matches[0].record.knowledge_id == "audit-chain-and-tamper-evidence"
    assert all(match.record.sources for match in korean.matches)
    assert exact.execution_authority is False
    assert console_sec.execution_authority is False


def test_unrelated_query_returns_complete_empty_result() -> None:
    result = SystemKnowledgeIndex(load_catalog(CATALOG_PATH)).search(
        _request("zxqv unrelated-token-4931")
    )

    assert result.outcome == "empty"
    assert result.matches == ()
    assert result.complete is True


def test_catalog_revision_fence_rejects_another_release() -> None:
    with pytest.raises(ValueError, match="source revision"):
        load_catalog(CATALOG_PATH, expected_source_revision="f" * 40)
