from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTOMATION = REPO_ROOT / "scripts" / "automation"
SCRIPT = AUTOMATION / "roadmap_verification.py"


def _load_module() -> ModuleType:
    sys.path.insert(0, str(AUTOMATION))
    spec = importlib.util.spec_from_file_location("fdai_roadmap_verification", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - test-controlled commands and paths
        arguments,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "docs/roadmap/architecture").mkdir(parents=True)
    (repo / "scripts/lib").mkdir(parents=True)
    (repo / "docs/roadmap/README.md").write_text("# Roadmap\n", encoding="utf-8")
    (repo / "docs/roadmap/README-ko.md").write_text("# Roadmap KO\n", encoding="utf-8")
    document = repo / "docs/roadmap/architecture/example.md"
    document.write_text("# Example\n", encoding="utf-8")
    document.with_name("example-ko.md").write_text("# Example KO\n", encoding="utf-8")
    (repo / "scripts/lib/design-routes.json").write_text(
        json.dumps(
            {
                "version": 1,
                "routes": [
                    {
                        "id": "baseline",
                        "paths": ["**"],
                        "must_read": [],
                        "validate": ["scripts/verify.sh"],
                    },
                    {
                        "id": "example",
                        "paths": ["src/example/**"],
                        "must_read": ["docs/roadmap/architecture/example.md"],
                        "docs_update": ["docs/roadmap/architecture/example.md"],
                        "validate": ["pytest tests/example"],
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert _run(repo, "git", "init", "--quiet", "--initial-branch=main").returncode == 0
    assert _run(repo, "git", "config", "user.email", "user@example.com").returncode == 0
    assert _run(repo, "git", "config", "user.name", "Example User").returncode == 0
    assert _run(repo, "git", "add", ".").returncode == 0
    assert _run(repo, "git", "commit", "--quiet", "-m", "initial").returncode == 0
    return repo


def test_sync_queues_only_canonical_docs_with_route_evidence(git_repo: Path) -> None:
    module = _load_module()
    paths = module.queue_paths(git_repo)

    assert module.sync(paths) == 2

    jobs = [json.loads(path.read_text(encoding="utf-8")) for path in paths.jobs.glob("*.json")]
    by_document = {job["document"]: job for job in jobs}
    assert set(by_document) == {
        "docs/roadmap/README.md",
        "docs/roadmap/architecture/example.md",
    }
    assert by_document["docs/roadmap/architecture/example.md"]["route_ids"] == [
        "baseline",
        "example",
    ]
    assert by_document["docs/roadmap/architecture/example.md"]["validation_commands"] == [
        "pytest tests/example",
    ]


def test_linked_worktree_uses_shared_queue(
    git_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.delenv("FDAI_ROADMAP_STATE_ROOT", raising=False)
    linked = tmp_path / "linked"
    added = _run(git_repo, "git", "worktree", "add", "--quiet", "--detach", str(linked))
    assert added.returncode == 0

    primary_paths = module.queue_paths(git_repo)
    linked_paths = module.queue_paths(linked)
    module.sync(primary_paths)

    assert linked_paths.state_root == primary_paths.state_root
    assert module.status(linked_paths) == {"queued": 2}


def test_explicit_state_root_supports_isolated_campaign_tools(
    git_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    state_root = tmp_path / "isolated-state"
    monkeypatch.setenv("FDAI_ROADMAP_STATE_ROOT", str(state_root))

    paths = module.queue_paths(git_repo)
    module.sync(paths)

    assert paths.state_root == state_root
    assert module.status(paths) == {"queued": 2}


def test_claim_recovers_expired_running_job(git_repo: Path) -> None:
    module = _load_module()
    paths = module.queue_paths(git_repo)
    start = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    module.sync(paths, now=start)
    first = module.claim(paths, owner="worker-a", lease_seconds=60, now=start)
    assert first is not None

    second = module.claim(
        paths,
        owner="worker-b",
        lease_seconds=60,
        now=start + timedelta(seconds=61),
    )

    assert second is not None
    assert second["job_id"] == first["job_id"]
    assert second["owner"] == "worker-b"
    assert second["attempts"] == 2
    ledger = [json.loads(line) for line in paths.ledger.read_text(encoding="utf-8").splitlines()]
    assert [record["action"] for record in ledger] == [
        "claimed",
        "stale_claim_recovered",
        "claimed",
    ]


def test_heartbeat_and_finish_require_the_claim_owner(git_repo: Path) -> None:
    module = _load_module()
    paths = module.queue_paths(git_repo)
    start = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    module.sync(paths, now=start)
    job = module.claim(paths, owner="worker-a", lease_seconds=60, now=start)
    assert job is not None

    with pytest.raises(RuntimeError, match="not owned"):
        module.heartbeat(
            paths,
            job_id=job["job_id"],
            owner="worker-b",
            checkpoint="auditing",
            lease_seconds=60,
            now=start,
        )

    renewed = module.heartbeat(
        paths,
        job_id=job["job_id"],
        owner="worker-a",
        checkpoint="focused_checks_passed",
        lease_seconds=60,
        details={"worktree": str(git_repo / "worktree")},
        now=start + timedelta(seconds=30),
    )
    assert renewed["checkpoint"] == "focused_checks_passed"
    assert renewed["checkpoint_details"] == {"worktree": str(git_repo / "worktree")}

    completed = module.finish(
        paths,
        job_id=job["job_id"],
        owner="worker-a",
        outcome="verified",
        result={"head": "abc123", "evidence_paths": ["tests/example.py"]},
        now=start + timedelta(seconds=31),
    )
    assert completed["status"] == "verified"
    assert "owner" not in completed
    receipt = json.loads((paths.receipts / f"{job['job_id']}.json").read_text(encoding="utf-8"))
    assert receipt["result"]["head"] == "abc123"


def test_sync_requeues_when_document_or_evidence_changes(git_repo: Path) -> None:
    module = _load_module()
    paths = module.queue_paths(git_repo)
    module.sync(paths)
    job = module.claim(paths, owner="worker-a", lease_seconds=60)
    assert job is not None
    evidence = "docs/roadmap/README.md"
    result = {
        "document_blob": module.inventory.file_blob(git_repo, job["document"]),
        "evidence_paths": [evidence],
        "evidence_digest": module.inventory.evidence_digest(git_repo, [evidence]),
    }
    module.finish(
        paths,
        job_id=job["job_id"],
        owner="worker-a",
        outcome="verified",
        result=result,
    )
    assert (paths.receipts / f"{job['job_id']}.json").is_file()

    target = git_repo / job["document"]
    target.write_text(target.read_text(encoding="utf-8") + "Changed.\n", encoding="utf-8")
    module.sync(paths)

    refreshed = json.loads((paths.jobs / f"{job['job_id']}.json").read_text(encoding="utf-8"))
    assert refreshed["status"] == "queued"
    assert "document_changed" in refreshed["stale_reasons"]
    assert not (paths.receipts / f"{job['job_id']}.json").exists()


def test_sync_requeues_when_route_mapping_changes(git_repo: Path) -> None:
    module = _load_module()
    paths = module.queue_paths(git_repo)
    module.sync(paths)
    jobs = [json.loads(path.read_text(encoding="utf-8")) for path in paths.jobs.glob("*.json")]
    job = next(value for value in jobs if value["document"].endswith("example.md"))
    claimed = module.claim(paths, owner="worker-a", lease_seconds=60)
    while claimed is not None and claimed["job_id"] != job["job_id"]:
        module.finish(
            paths,
            job_id=claimed["job_id"],
            owner="worker-a",
            outcome="blocked",
            result={},
        )
        claimed = module.claim(paths, owner="worker-a", lease_seconds=60)
    assert claimed is not None
    module.finish(
        paths,
        job_id=claimed["job_id"],
        owner="worker-a",
        outcome="designed",
        result={},
    )
    routes_path = git_repo / "scripts/lib/design-routes.json"
    routes = json.loads(routes_path.read_text(encoding="utf-8"))
    routes["routes"][1]["validate"].append("pytest tests/another")
    routes_path.write_text(json.dumps(routes) + "\n", encoding="utf-8")

    module.sync(paths)

    refreshed = json.loads((paths.jobs / f"{claimed['job_id']}.json").read_text(encoding="utf-8"))
    assert refreshed["status"] == "queued"
    assert refreshed["stale_reasons"] == ["route_mapping_changed"]
