"""CollectorPipeline + fetchers + CLI — fully offline tests.

Git and HTTP fetchers are exercised via local git bare repos and
``file://`` URLs so the test suite has zero external network dependency.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from aiopspilot.rule_catalog.pipeline.collect import (
    CollectorPipeline,
    HttpDownloadFetcher,
    LocalDirectoryFetcher,
)
from aiopspilot.rule_catalog.pipeline.collect.collector import (
    _count_files,
    _hash_tree,
    _short_revision,
)
from aiopspilot.rule_catalog.pipeline.collect.fetch import (
    FetchError,
    GitCloneFetcher,
    build_fetcher,
)
from aiopspilot.rule_catalog.pipeline.collect_cli import main as cli_main
from aiopspilot.rule_catalog.schema.source_manifest import (
    FetchConfig,
    FetchKind,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Helpers + fixtures
# ---------------------------------------------------------------------------


def _write_source_tree(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "policy.rego").write_text("package foo\ndeny = false\n", encoding="utf-8")
    sub = root / "sub"
    sub.mkdir()
    (sub / "policy.yaml").write_text("id: sample\nseverity: low\n", encoding="utf-8")


def _write_manifest(path: Path, source_path: str, *, source_id: str = "smoke-src") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "id": source_id,
                "name": "Smoke",
                "license": "Apache-2.0",
                "redistribution": "embeddable",
                "fetch": {"kind": "local", "path": source_path},
                "parser": "rule-yaml",
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# LocalDirectoryFetcher
# ---------------------------------------------------------------------------


def test_local_fetcher_copies_tree(tmp_path: Path) -> None:
    source = tmp_path / "src"
    _write_source_tree(source)
    dest = tmp_path / "dest"
    fetcher = LocalDirectoryFetcher(repo_root=tmp_path)
    result = fetcher.fetch(
        config=FetchConfig(kind=FetchKind.LOCAL, path=str(source)),
        dest_root=dest,
    )
    assert result.tree_root == dest
    assert (dest / "policy.rego").exists()
    assert (dest / "sub" / "policy.yaml").exists()


def test_local_fetcher_resolves_relative_path(tmp_path: Path) -> None:
    source = tmp_path / "seed"
    _write_source_tree(source)
    dest = tmp_path / "dest"
    fetcher = LocalDirectoryFetcher(repo_root=tmp_path)
    result = fetcher.fetch(
        config=FetchConfig(kind=FetchKind.LOCAL, path="seed"),
        dest_root=dest,
    )
    assert (dest / "policy.rego").exists()
    assert result.resolved_revision.endswith("/seed")


def test_local_fetcher_raises_on_missing(tmp_path: Path) -> None:
    fetcher = LocalDirectoryFetcher(repo_root=tmp_path)
    with pytest.raises(FetchError, match="not found"):
        fetcher.fetch(
            config=FetchConfig(kind=FetchKind.LOCAL, path=str(tmp_path / "nope")),
            dest_root=tmp_path / "dest",
        )


def test_local_fetcher_rejects_git_kind(tmp_path: Path) -> None:
    fetcher = LocalDirectoryFetcher(repo_root=tmp_path)
    with pytest.raises(FetchError, match="does not handle"):
        fetcher.fetch(
            config=FetchConfig(
                kind=FetchKind.GIT,
                repo="https://x/y",
                revision="0" * 40,
            ),
            dest_root=tmp_path,
        )


def test_local_fetcher_construction_rejects_missing_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="directory"):
        LocalDirectoryFetcher(repo_root=tmp_path / "missing")


def test_local_fetcher_handles_file_source(tmp_path: Path) -> None:
    """A ``path`` that points at a file (not a dir) is copied by name."""
    src_file = tmp_path / "single.yaml"
    src_file.write_text("id: solo\nseverity: low\n", encoding="utf-8")
    dest = tmp_path / "dest"
    fetcher = LocalDirectoryFetcher(repo_root=tmp_path)
    result = fetcher.fetch(
        config=FetchConfig(kind=FetchKind.LOCAL, path=str(src_file)),
        dest_root=dest,
    )
    assert (dest / "single.yaml").is_file()
    assert result.resolved_revision == str(src_file)


def test_build_fetcher_dispatch(tmp_path: Path) -> None:
    assert isinstance(build_fetcher(FetchKind.LOCAL, repo_root=tmp_path), LocalDirectoryFetcher)
    assert isinstance(build_fetcher(FetchKind.GIT, repo_root=tmp_path), GitCloneFetcher)
    assert isinstance(build_fetcher(FetchKind.HTTP, repo_root=tmp_path), HttpDownloadFetcher)


def test_git_fetcher_construction_guards() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        GitCloneFetcher(timeout_seconds=0)


def test_git_fetcher_rejects_non_git_kind(tmp_path: Path) -> None:
    fetcher = GitCloneFetcher()
    with pytest.raises(FetchError, match="does not handle"):
        fetcher.fetch(
            config=FetchConfig(kind=FetchKind.LOCAL, path=str(tmp_path)),
            dest_root=tmp_path,
        )


# ---------------------------------------------------------------------------
# GitCloneFetcher against a local bare repo (no network)
# ---------------------------------------------------------------------------


def _has_git() -> bool:
    return shutil.which("git") is not None


def _init_local_git_source(root: Path) -> tuple[Path, str]:
    """Init a git working tree with one commit and return (bare_repo, commit_sha).

    The bare repo lives alongside the working tree; ``GitCloneFetcher``
    treats it as a remote URL just like a network origin.
    """
    work = root / "work"
    work.mkdir()
    (work / "policy.rego").write_text("package git_fixture\ndeny = true\n", encoding="utf-8")
    sub = work / "sub"
    sub.mkdir()
    (sub / "rule.yaml").write_text("id: git-sample\nseverity: high\n", encoding="utf-8")

    env = {
        "GIT_AUTHOR_NAME": "collector-test",
        "GIT_AUTHOR_EMAIL": "collector@example.com",
        "GIT_COMMITTER_NAME": "collector-test",
        "GIT_COMMITTER_EMAIL": "collector@example.com",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }

    def _run(argv: list[str], cwd: Path) -> str:
        proc = subprocess.run(  # noqa: S603 — argv is a list.
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        return proc.stdout.strip()

    _run(["git", "init", "-q", "-b", "main"], work)
    _run(["git", "add", "."], work)
    _run(["git", "commit", "-q", "-m", "seed"], work)
    sha = _run(["git", "rev-parse", "HEAD"], work)

    bare = root / "origin.git"
    _run(["git", "clone", "--bare", "-q", str(work), str(bare)], root)
    return bare, sha


@pytest.mark.skipif(not _has_git(), reason="git binary not on PATH")
def test_git_fetcher_clones_pinned_revision(tmp_path: Path) -> None:
    bare, sha = _init_local_git_source(tmp_path)
    fetcher = GitCloneFetcher(timeout_seconds=30.0)
    dest = tmp_path / "snap"
    result = fetcher.fetch(
        config=FetchConfig(kind=FetchKind.GIT, repo=str(bare), revision=sha),
        dest_root=dest,
    )
    assert result.resolved_revision == sha
    assert (result.tree_root / "policy.rego").is_file()
    assert (result.tree_root / "sub" / "rule.yaml").is_file()
    # Never leak the .git metadata into the snapshot tree.
    assert not (result.tree_root / ".git").exists()


@pytest.mark.skipif(not _has_git(), reason="git binary not on PATH")
def test_git_fetcher_honors_subpath(tmp_path: Path) -> None:
    bare, sha = _init_local_git_source(tmp_path)
    fetcher = GitCloneFetcher(timeout_seconds=30.0)
    dest = tmp_path / "snap"
    result = fetcher.fetch(
        config=FetchConfig(
            kind=FetchKind.GIT,
            repo=str(bare),
            revision=sha,
            subpath="sub",
        ),
        dest_root=dest,
    )
    assert (result.tree_root / "rule.yaml").is_file()
    assert not (result.tree_root / "policy.rego").exists()


@pytest.mark.skipif(not _has_git(), reason="git binary not on PATH")
def test_git_fetcher_raises_on_missing_subpath(tmp_path: Path) -> None:
    bare, sha = _init_local_git_source(tmp_path)
    fetcher = GitCloneFetcher(timeout_seconds=30.0)
    with pytest.raises(FetchError, match="subpath"):
        fetcher.fetch(
            config=FetchConfig(
                kind=FetchKind.GIT,
                repo=str(bare),
                revision=sha,
                subpath="does-not-exist",
            ),
            dest_root=tmp_path / "snap",
        )


@pytest.mark.skipif(not _has_git(), reason="git binary not on PATH")
def test_git_fetcher_reports_git_failure(tmp_path: Path) -> None:
    fetcher = GitCloneFetcher(timeout_seconds=10.0)
    with pytest.raises(FetchError, match="failed with exit"):
        fetcher.fetch(
            config=FetchConfig(
                kind=FetchKind.GIT,
                repo=str(tmp_path / "does-not-exist"),
                revision="0" * 40,
            ),
            dest_root=tmp_path / "snap",
        )


# ---------------------------------------------------------------------------
# HttpDownloadFetcher against file:// URLs (no network)
# ---------------------------------------------------------------------------


def _file_url(path: Path) -> str:
    return path.resolve().as_uri()


def test_http_fetcher_downloads_and_verifies(tmp_path: Path) -> None:
    payload = tmp_path / "seed.tgz"
    body = b"pretend-tarball-bytes"
    payload.write_bytes(body)
    expected = hashlib.sha256(body).hexdigest()

    fetcher = HttpDownloadFetcher(timeout_seconds=10.0)
    dest = tmp_path / "snap"
    result = fetcher.fetch(
        config=FetchConfig(
            kind=FetchKind.HTTP,
            url=_file_url(payload),
            expected_sha256=expected,
        ),
        dest_root=dest,
    )
    assert result.resolved_revision == expected
    assert (dest / "seed.tgz").read_bytes() == body


def test_http_fetcher_rejects_bad_hash(tmp_path: Path) -> None:
    payload = tmp_path / "seed.tgz"
    payload.write_bytes(b"actual-bytes")

    fetcher = HttpDownloadFetcher(timeout_seconds=10.0)
    with pytest.raises(FetchError, match="sha256 mismatch"):
        fetcher.fetch(
            config=FetchConfig(
                kind=FetchKind.HTTP,
                url=_file_url(payload),
                expected_sha256="0" * 64,
            ),
            dest_root=tmp_path / "snap",
        )
    # The mismatched payload MUST NOT remain on disk.
    assert not (tmp_path / "snap" / "seed.tgz").exists()


def test_http_fetcher_rejects_unsupported_scheme(tmp_path: Path) -> None:
    fetcher = HttpDownloadFetcher(timeout_seconds=1.0)
    with pytest.raises(FetchError, match="scheme"):
        fetcher.fetch(
            config=FetchConfig(
                kind=FetchKind.HTTP,
                url="ftp://example.com/x.tar.gz",
                expected_sha256="0" * 64,
            ),
            dest_root=tmp_path / "snap",
        )


def test_http_fetcher_rejects_non_http_kind(tmp_path: Path) -> None:
    fetcher = HttpDownloadFetcher(timeout_seconds=1.0)
    with pytest.raises(FetchError, match="does not handle"):
        fetcher.fetch(
            config=FetchConfig(kind=FetchKind.LOCAL, path=str(tmp_path)),
            dest_root=tmp_path / "snap",
        )


def test_http_fetcher_raises_on_network_error(tmp_path: Path) -> None:
    fetcher = HttpDownloadFetcher(timeout_seconds=1.0)
    missing = tmp_path / "missing.bin"
    with pytest.raises(FetchError, match="download failed"):
        fetcher.fetch(
            config=FetchConfig(
                kind=FetchKind.HTTP,
                url=_file_url(missing),
                expected_sha256="0" * 64,
            ),
            dest_root=tmp_path / "snap",
        )


def test_http_fetcher_synthetic_filename_when_url_has_no_name(tmp_path: Path) -> None:
    """A URL ending in ``/`` MUST land under ``payload`` — the sink name stays predictable."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_bytes(b"root-doc")
    # `file://.../site/` — trailing slash, no filename in the path.
    url = site.resolve().as_uri() + "/"
    fetcher = HttpDownloadFetcher(timeout_seconds=5.0)
    dest = tmp_path / "snap"
    # urlopen on a directory file:// URL raises OSError → wrapped in FetchError.
    with pytest.raises(FetchError):
        fetcher.fetch(
            config=FetchConfig(
                kind=FetchKind.HTTP,
                url=url,
                expected_sha256=hashlib.sha256(b"root-doc").hexdigest(),
            ),
            dest_root=dest,
        )


def test_http_fetcher_construction_guards() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        HttpDownloadFetcher(timeout_seconds=0)
    with pytest.raises(ValueError, match="chunk_bytes"):
        HttpDownloadFetcher(chunk_bytes=0)


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------


def test_hash_tree_is_deterministic(tmp_path: Path) -> None:
    src = tmp_path / "s"
    _write_source_tree(src)
    h1 = _hash_tree(src)
    h2 = _hash_tree(src)
    assert h1 == h2
    assert len(h1) == 64


def test_hash_tree_changes_when_content_changes(tmp_path: Path) -> None:
    src = tmp_path / "s"
    _write_source_tree(src)
    h1 = _hash_tree(src)
    (src / "extra.txt").write_text("delta\n", encoding="utf-8")
    h2 = _hash_tree(src)
    assert h1 != h2


def test_short_revision_alnum_is_truncated() -> None:
    assert _short_revision("abcdef0123456789") == "abcdef012345"
    assert _short_revision("abc123") == "abc123"


def test_short_revision_non_alnum_is_hashed() -> None:
    a = _short_revision("/some/path/with/slashes")
    b = _short_revision("/some/path/with/slashes")
    assert a == b
    assert len(a) == 12


def test_count_files(tmp_path: Path) -> None:
    src = tmp_path / "s"
    _write_source_tree(src)
    assert _count_files(src) == 2


# ---------------------------------------------------------------------------
# CollectorPipeline
# ---------------------------------------------------------------------------


def test_collector_writes_snapshot_and_provenance(tmp_path: Path) -> None:
    source = tmp_path / "seed"
    _write_source_tree(source)
    manifest_path = tmp_path / "manifest.yaml"
    _write_manifest(manifest_path, str(source))

    pipeline = CollectorPipeline(
        repo_root=tmp_path,
        output_root=tmp_path / "snapshots",
    )
    report = pipeline.collect_from_manifest_path(manifest_path)

    assert report.source_id == "smoke-src"
    assert report.file_count == 2
    assert report.snapshot_dir.exists()
    tree_dir = report.snapshot_dir / "tree"
    assert (tree_dir / "policy.rego").exists()
    assert (tree_dir / "sub" / "policy.yaml").exists()

    provenance = json.loads((report.snapshot_dir / "SNAPSHOT.json").read_text())
    assert provenance["source_id"] == "smoke-src"
    assert provenance["content_sha256"] == report.content_sha256
    assert provenance["parser"] == "rule-yaml"


def test_collector_dry_run_does_not_write(tmp_path: Path) -> None:
    source = tmp_path / "seed"
    _write_source_tree(source)
    manifest_path = tmp_path / "manifest.yaml"
    _write_manifest(manifest_path, str(source))
    out = tmp_path / "snapshots"

    pipeline = CollectorPipeline(repo_root=tmp_path, output_root=out)
    report = pipeline.collect_from_manifest_path(manifest_path, dry_run=True)
    assert report.file_count == 2
    assert not out.exists()


def test_collector_replaces_existing_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "seed"
    _write_source_tree(source)
    manifest_path = tmp_path / "manifest.yaml"
    _write_manifest(manifest_path, str(source))
    out = tmp_path / "snapshots"

    pipeline = CollectorPipeline(repo_root=tmp_path, output_root=out)
    first = pipeline.collect_from_manifest_path(manifest_path)
    # A stale file left in the snapshot dir MUST be cleared on the second run.
    (first.snapshot_dir / "stale.txt").write_text("stale\n", encoding="utf-8")
    second = pipeline.collect_from_manifest_path(manifest_path)
    assert not (second.snapshot_dir / "stale.txt").exists()
    assert first.content_sha256 == second.content_sha256


def test_collector_repo_root_must_be_directory(tmp_path: Path) -> None:
    bogus = tmp_path / "missing"
    with pytest.raises(ValueError, match="directory"):
        CollectorPipeline(repo_root=bogus)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_runs_dry_run_against_local_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "seed"
    _write_source_tree(source)
    manifest_path = tmp_path / "manifest.yaml"
    _write_manifest(manifest_path, str(source))
    out = tmp_path / "snapshots"

    exit_code = cli_main(
        [
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(tmp_path),
            "--output-root",
            str(out),
            "--dry-run",
        ]
    )
    assert exit_code == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["source_id"] == "smoke-src"
    assert payload["dry_run"] is True


def test_cli_fails_on_bad_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- not a mapping\n", encoding="utf-8")
    exit_code = cli_main(
        [
            "--manifest",
            str(bad),
            "--repo-root",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 2
    assert "error" in capsys.readouterr().err


def test_cli_writes_snapshot_and_prints_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Non-dry-run path — snapshot is materialized, summary lands on stdout."""
    source = tmp_path / "seed"
    _write_source_tree(source)
    manifest_path = tmp_path / "manifest.yaml"
    _write_manifest(manifest_path, str(source), source_id="cli-write")
    out = tmp_path / "snapshots"

    exit_code = cli_main(
        [
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(tmp_path),
            "--output-root",
            str(out),
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is False
    assert payload["mismatch"] is None
    snapshot_dir = Path(payload["snapshot_dir"])
    assert (snapshot_dir / "SNAPSHOT.json").is_file()
    assert (snapshot_dir / "tree" / "policy.rego").is_file()


def test_cli_reports_hash_mismatch_as_nonzero_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An HTTP manifest whose payload sha differs from ``expected_sha256`` exits 2."""
    payload_bytes = b"actual-body"
    payload_path = tmp_path / "seed.tgz"
    payload_path.write_bytes(payload_bytes)

    manifest_path = tmp_path / "http-manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "id": "cli-http-mismatch",
                "name": "HTTP mismatch",
                "license": "Apache-2.0",
                "redistribution": "embeddable",
                "fetch": {
                    "kind": "http",
                    "url": payload_path.resolve().as_uri(),
                    # Deliberately wrong so the pipeline records a mismatch.
                    "expected_sha256": "0" * 64,
                },
                "parser": "rule-yaml",
            }
        ),
        encoding="utf-8",
    )

    # HTTP mismatch flows through the fetcher (FetchError) rather than the
    # pipeline's own mismatch record — either way, exit is non-zero.
    exit_code = cli_main(
        [
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "snapshots"),
        ]
    )
    assert exit_code == 2
    assert "error" in capsys.readouterr().err


def test_cli_auto_detects_repo_root_when_omitted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omit ``--repo-root``; the CLI walks up until a ``rule-catalog/`` dir appears."""
    # A tmp workspace with a rule-catalog/ sibling — the same shape the
    # process entrypoint expects.
    workspace = tmp_path / "workspace"
    (workspace / "rule-catalog").mkdir(parents=True)
    source = workspace / "seed"
    _write_source_tree(source)
    manifest_path = workspace / "manifest.yaml"
    _write_manifest(manifest_path, str(source), source_id="cli-autoroot")

    monkeypatch.chdir(workspace)
    exit_code = cli_main(
        [
            "--manifest",
            str(manifest_path),
            "--output-root",
            str(workspace / "snapshots"),
            "--dry-run",
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source_id"] == "cli-autoroot"


# ---------------------------------------------------------------------------
# CollectorPipeline end-to-end against the shipped self-hosted manifest
# ---------------------------------------------------------------------------


def test_collector_produces_snapshot_of_shipped_seed_manifest(tmp_path: Path) -> None:
    """The shipped ``aiopspilot-p1-seed`` manifest MUST snapshot without error.

    Uses the real repo root (this file's parent chain) so a regression in
    either the manifest or the LocalDirectoryFetcher shows up here.
    """
    manifest_path = REPO_ROOT / "rule-catalog" / "sources" / "aiopspilot-p1-seed" / "manifest.yaml"
    assert manifest_path.exists(), f"shipped manifest missing: {manifest_path}"

    pipeline = CollectorPipeline(
        repo_root=REPO_ROOT,
        output_root=tmp_path / "snapshots",
    )
    report = pipeline.collect_from_manifest_path(manifest_path)
    assert report.source_id == "aiopspilot-p1-seed"
    assert report.file_count >= 50, (
        f"seed manifest should carry the 50-rule catalog; saw {report.file_count}"
    )
    provenance = json.loads((report.snapshot_dir / "SNAPSHOT.json").read_text())
    assert provenance["parser"] == "rule-yaml"
    assert provenance["license"] == "Apache-2.0"


def test_collector_records_http_mismatch_when_fetcher_skips_validation(tmp_path: Path) -> None:
    """Defense-in-depth: even if a custom fetcher fails to check the hash,
    the pipeline's own compare against ``expected_sha256`` MUST land the
    mismatch on the report and refuse to materialize a snapshot.
    """
    from aiopspilot.rule_catalog.pipeline.collect.fetch import FetchResult
    from aiopspilot.rule_catalog.schema.source_manifest import SourceManifest

    class _NoValidateHttpFetcher:
        """Stand-in fetcher that returns without verifying the hash."""

        def fetch(self, *, config: FetchConfig, dest_root: Path) -> FetchResult:  # noqa: ARG002
            dest_root.mkdir(parents=True, exist_ok=True)
            (dest_root / "payload.bin").write_bytes(b"content-differs")
            return FetchResult(tree_root=dest_root, resolved_revision="stubbed-revision")

    manifest = SourceManifest.model_validate(
        {
            "schema_version": "1.0.0",
            "id": "pipeline-http-guard",
            "name": "guard",
            "license": "Apache-2.0",
            "redistribution": "embeddable",
            "fetch": {
                "kind": "http",
                "url": "https://example.com/x.bin",
                "expected_sha256": "0" * 64,
            },
            "parser": "rule-yaml",
        }
    )

    pipeline = CollectorPipeline(
        repo_root=tmp_path,
        output_root=tmp_path / "snapshots",
        fetcher=_NoValidateHttpFetcher(),
    )
    report = pipeline.collect(manifest)
    assert report.mismatch is not None
    assert "expected_sha256" in report.mismatch
    # A mismatch MUST NOT materialize a snapshot on disk.
    assert not (tmp_path / "snapshots" / "pipeline-http-guard").exists()


# ---------------------------------------------------------------------------
# CLI --verify path (collect + parse + verify end-to-end)
# ---------------------------------------------------------------------------


def test_cli_verify_flag_reports_verified_count_on_shipped_seed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--verify`` against the shipped seed manifest exits 0 with issues=[]."""
    manifest_path = REPO_ROOT / "rule-catalog" / "sources" / "aiopspilot-p1-seed" / "manifest.yaml"
    exit_code = cli_main(
        [
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(REPO_ROOT),
            "--output-root",
            str(tmp_path / "snapshots"),
            "--verify",
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    verify = payload["verify"]
    assert verify["parser"] == "rule-yaml"
    assert verify["parsed"] >= 50
    assert verify["verified"] >= 50
    assert verify["issues"] == []


def test_cli_verify_flag_skipped_on_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--verify --dry-run`` reports a skip marker instead of parsing anything."""
    source = tmp_path / "seed"
    _write_source_tree(source)
    manifest_path = tmp_path / "manifest.yaml"
    _write_manifest(manifest_path, str(source), source_id="cli-verify-dry")

    exit_code = cli_main(
        [
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "snapshots"),
            "--verify",
            "--dry-run",
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verify"]["skipped"] == "dry-run"


def test_cli_verify_flag_reports_verification_issues(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A snapshot whose rule points at an unknown ActionType exits 2 with issues."""
    # Craft a source tree with a rule that references a bogus ActionType.
    source = tmp_path / "seed"
    source.mkdir()
    (source / "bogus.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "id": "bogus.action.example",
                "version": "1.0.0",
                "source": "custom",
                "severity": "low",
                "category": "config_drift",
                "resource_type": "object-storage",
                "check_logic": {"kind": "rego", "reference": "inline://nope"},
                "remediation": {"template_ref": "inline://nope"},
                "remediates": "remediate.does-not-exist",
                "provenance": {
                    "source_url": "https://example.com/bogus",
                    "resolved_ref": "0" * 40,
                    "content_hash": "sha256:" + "0" * 64,
                    "license": "LicenseRef-reference-only",
                    "redistribution": "reference-only",
                    "retrieved_at": "2026-07-06T00:00:00Z",
                },
            }
        ),
        encoding="utf-8",
    )

    manifest_path = tmp_path / "manifest.yaml"
    _write_manifest(manifest_path, str(source), source_id="cli-verify-fail")

    exit_code = cli_main(
        [
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "snapshots"),
            "--verify",
            "--catalog-root",
            str(REPO_ROOT / "rule-catalog"),
        ]
    )
    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["verify"]["verified"] == 0
    assert any("unknown ActionType" in i["message"] for i in payload["verify"]["issues"])


def test_cli_verify_flag_errors_on_missing_catalog_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--verify`` with a bogus ``--catalog-root`` exits 2 with an error."""
    source = tmp_path / "seed"
    _write_source_tree(source)
    manifest_path = tmp_path / "manifest.yaml"
    _write_manifest(manifest_path, str(source), source_id="cli-verify-missing")

    exit_code = cli_main(
        [
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "snapshots"),
            "--verify",
            "--catalog-root",
            str(tmp_path / "no-catalog-here"),
        ]
    )
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "catalog root missing" in captured.err
    payload = json.loads(captured.out)
    assert "error" in payload["verify"]


def test_cli_verify_flag_reports_parse_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "seed"
    source.mkdir()
    (source / "broken.yaml").write_text("id: [unterminated\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.yaml"
    _write_manifest(manifest_path, str(source), source_id="cli-verify-parse-err")

    exit_code = cli_main(
        [
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "snapshots"),
            "--verify",
        ]
    )
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "invalid YAML" in captured.err
    payload = json.loads(captured.out)
    assert "error" in payload["verify"]


def test_cli_verify_flag_reports_not_implemented_parser(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A manifest referencing a declared-but-unimplemented parser exits 2."""
    source = tmp_path / "seed"
    _write_source_tree(source)
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "id": "cli-verify-notimpl",
                "name": "Not implemented parser",
                "license": "Apache-2.0",
                "redistribution": "embeddable",
                "fetch": {"kind": "local", "path": str(source)},
                # `azure-policy-json` is a declared parser but has no
                # built-in adapter yet — swap this to the next-added
                # parser once implemented.
                "parser": "azure-policy-json",
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli_main(
        [
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "snapshots"),
            "--verify",
        ]
    )
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "azure-policy-json" in captured.err
    payload = json.loads(captured.out)
    assert "error" in payload["verify"]


def test_cli_repo_root_fallback_uses_cwd_when_no_rule_catalog_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_repo_root`` returns cwd when no ancestor has a ``rule-catalog/`` dir."""
    from aiopspilot.rule_catalog.pipeline import collect_cli

    # Point Path(__file__) resolution deep into a tmp tree without any
    # ``rule-catalog`` sibling on the way up.
    fake_leaf = tmp_path / "a" / "b" / "c" / "collect_cli.py"
    fake_leaf.parent.mkdir(parents=True)
    fake_leaf.write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(collect_cli, "__file__", str(fake_leaf))
    monkeypatch.chdir(tmp_path)
    assert collect_cli._repo_root() == tmp_path.resolve()
