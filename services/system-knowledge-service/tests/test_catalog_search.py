from __future__ import annotations

import runpy
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import fdai_system_knowledge_service.build_catalog as build_catalog_module
import fdai_system_knowledge_service.catalog as catalog_module
import fdai_system_knowledge_service.render as render_module
import pytest
from fdai_service_contracts.system_knowledge import (
    SystemKnowledgeAuthorityRole,
    SystemKnowledgeMatch,
    SystemKnowledgeQueryRequest,
    SystemKnowledgeQueryResponse,
    SystemKnowledgeRecord,
    SystemKnowledgeSource,
    SystemKnowledgeSourceKind,
    SystemKnowledgeStatus,
    system_knowledge_digest,
)
from fdai_system_knowledge_service.catalog import (
    _compile_source,
    _find_symbol,
    _git_output,
    _require_git,
    _resolve_ancestor_revision,
    compile_reference_catalog,
    load_catalog,
    resolve_protected_main_revision,
    write_catalog,
)
from fdai_system_knowledge_service.render import (
    outgoing_webhook_payload,
    render_answer,
    teams_payload,
)
from fdai_system_knowledge_service.search import SystemKnowledgeIndex, _singular
from fdai_system_knowledge_service.seeds import KnowledgeSeed, SeedSource

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXED_TIME = datetime(2026, 9, 9, tzinfo=UTC)
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


def test_catalog_compiler_cli_and_error_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_at(repo, "init", "--quiet", "--initial-branch", "main")
    _git_at(repo, "config", "user.email", "tests@example.com")
    _git_at(repo, "config", "user.name", "FDAI Tests")
    (repo / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (repo / "ignored.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "mod.py").write_text("value = 'inline_symbol_token'\n", encoding="utf-8")
    _git_at(repo, "add", ".gitignore", "mod.py")
    _git_at(repo, "commit", "--quiet", "-m", "initial")
    main_sha = _git_at(repo, "rev-parse", "HEAD").stdout.strip()
    _git_at(repo, "update-ref", "refs/remotes/origin/main", main_sha)

    seed = KnowledgeSeed(
        knowledge_id="test-seed",
        subject_id="subject-test",
        title="Test Seed",
        status=SystemKnowledgeStatus.VALIDATED,
        owner="tests",
        question_aliases=("How does test seed work?",),
        designed_behavior=("Deterministic behavior.",),
        implemented_behavior=("Implemented behavior.",),
        limitations=("Bounded limitation.",),
        sources=(
            SeedSource(
                source_kind=SystemKnowledgeSourceKind.CODE,
                authority_role=SystemKnowledgeAuthorityRole.IMPLEMENTATION,
                path="mod.py",
                symbol="inline_symbol_token",
            ),
        ),
    )
    monkeypatch.setattr(catalog_module, "REFERENCE_SEEDS", (seed,))
    compiled = compile_reference_catalog(repo, generated_at=FIXED_TIME)
    out_path = tmp_path / "out" / "catalog.json"
    write_catalog(compiled, out_path)
    loaded = load_catalog(out_path, expected_source_revision=main_sha)
    assert loaded.catalog_digest == compiled.catalog_digest

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fdai-build-system-knowledge-catalog",
            "--repo-root",
            str(repo),
            "--output",
            str(out_path),
        ],
    )
    assert build_catalog_module.main() == 0
    assert build_catalog_module.__file__ is not None
    with pytest.raises(SystemExit) as exited:
        runpy.run_path(build_catalog_module.__file__, run_name="__main__")
    assert exited.value.code == 0

    with pytest.raises(ValueError, match="escaped the repository"):
        _compile_source(
            repo,
            SeedSource(
                source_kind=SystemKnowledgeSourceKind.CODE,
                authority_role=SystemKnowledgeAuthorityRole.IMPLEMENTATION,
                path="../outside.py",
                symbol="x",
            ),
        )
    with pytest.raises(FileNotFoundError, match="missing"):
        _compile_source(
            repo,
            SeedSource(
                source_kind=SystemKnowledgeSourceKind.CODE,
                authority_role=SystemKnowledgeAuthorityRole.IMPLEMENTATION,
                path="missing.py",
                symbol="x",
            ),
        )
    with pytest.raises(ValueError, match="ignored"):
        _compile_source(
            repo,
            SeedSource(
                source_kind=SystemKnowledgeSourceKind.CODE,
                authority_role=SystemKnowledgeAuthorityRole.IMPLEMENTATION,
                path="ignored.py",
                symbol="x",
            ),
        )
    with pytest.raises(ValueError, match="symbol is missing"):
        _find_symbol(["def other(): pass"], "missing_symbol")

    _git_at(repo, "switch", "--quiet", "-c", "side")
    (repo / "mod.py").write_text("value = 'side'\n", encoding="utf-8")
    _git_at(repo, "commit", "--quiet", "-am", "side")
    side_sha = _git_at(repo, "rev-parse", "HEAD").stdout.strip()
    _git_at(repo, "switch", "--quiet", "main")
    with pytest.raises(ValueError, match="ancestor of HEAD"):
        _resolve_ancestor_revision(repo, side_sha)

    with pytest.raises(ValueError, match="Git identity is invalid"):
        _git_output(repo, "status", "--short")

    monkeypatch.setattr(catalog_module, "_GIT", None)
    with pytest.raises(RuntimeError, match="git is required"):
        _require_git()


def test_search_and_render_edge_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = load_catalog(CATALOG_PATH)
    index = SystemKnowledgeIndex(catalog, clock=lambda: FIXED_TIME)
    assert index.catalog == catalog

    punctuation_only = index.search(_request("??? !!!"))
    assert punctuation_only.outcome == "empty"
    assert _singular("policies") == "policy"
    assert _singular("actions") == "action"
    assert _singular("pass") == "pass"

    assert "검증된 FDAI" in render_answer(punctuation_only, locale="ko")
    assert "No verified FDAI" in render_answer(punctuation_only, locale="en")

    source = SystemKnowledgeSource(
        source_kind=SystemKnowledgeSourceKind.CODE,
        authority_role=SystemKnowledgeAuthorityRole.DESIGN,
        path="docs/example.md",
        symbol="Example",
        line_start=1,
        line_end=1,
        blob_sha="a" * 40,
    )
    record_body = {
        "knowledge_id": "minimal-record",
        "subject_id": "minimal-subject",
        "title": "Minimal Record",
        "status": SystemKnowledgeStatus.VALIDATED,
        "owner": "owner-example",
        "question_aliases": ("minimal?",),
        "designed_behavior": ("Designed only.",),
        "implemented_behavior": (),
        "limitations": (),
        "sources": (source,),
        "execution_authority": False,
    }
    record = SystemKnowledgeRecord.model_validate(
        {**record_body, "record_digest": system_knowledge_digest(record_body)}
    )
    match = SystemKnowledgeMatch(record=record, score=10.0, match_kind="exact_alias")
    resp_body = {
        "schema_version": "1.0.0",
        "outcome": "answered",
        "matches": (match,),
        "observed_at": FIXED_TIME,
        "source_revision": "a" * 40,
        "catalog_digest": catalog.catalog_digest,
        "complete": True,
        "limitation": None,
        "execution_authority": False,
    }
    response = SystemKnowledgeQueryResponse.model_validate(
        {**resp_body, "response_digest": system_knowledge_digest(resp_body)}
    )
    rendered = render_answer(response, locale="en")
    assert "Implemented evidence" not in rendered
    assert "Limitations" not in rendered

    monkeypatch.setattr(render_module, "_MAX_PAYLOAD_BYTES", 10)
    fallback_bot = teams_payload(response, locale="en", reply_to_id="msg-1")
    fallback_webhook = outgoing_webhook_payload(response, locale="en")
    assert "attachments" not in fallback_bot
    assert "attachments" not in fallback_webhook
