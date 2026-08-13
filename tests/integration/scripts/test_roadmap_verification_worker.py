from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
AUTOMATION = REPO_ROOT / "scripts" / "automation"
SCRIPT = AUTOMATION / "roadmap_verification_worker.py"


def _load_module() -> ModuleType:
    sys.path.insert(0, str(AUTOMATION))
    spec = importlib.util.spec_from_file_location("fdai_roadmap_verification_worker", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_report_command_has_no_write_tool_and_denies_side_effects(tmp_path: Path) -> None:
    _load_module()
    agent = sys.modules["roadmap_verification_agent"]
    command = agent.copilot_command(tmp_path / "copilot", "prompt", tmp_path, apply=False)

    assert "--available-tools=read,glob,grep,shell" in command
    assert "--available-tools=read,glob,grep,shell,write" not in command
    assert "--deny-tool=shell(git push)" in command
    assert "--deny-tool=shell(git commit)" in command
    assert "--deny-tool=shell(terraform)" in command
    assert "--disable-builtin-mcps" in command


def test_apply_command_allows_worktree_writes_but_still_denies_push(tmp_path: Path) -> None:
    _load_module()
    agent = sys.modules["roadmap_verification_agent"]
    command = agent.copilot_command(tmp_path / "copilot", "prompt", tmp_path, apply=True)

    assert "--available-tools=read,glob,grep,shell,write" in command
    assert "--allow-all-paths" not in command
    assert "--allow-all-urls" not in command
    assert "--deny-tool=shell(git push)" in command


def test_result_validation_rejects_evidence_outside_worktree(tmp_path: Path) -> None:
    _load_module()
    agent = sys.modules["roadmap_verification_agent"]
    (tmp_path / "evidence.py").write_text("pass\n", encoding="utf-8")

    validated = agent.validate_result(
        {
            "outcome": "reviewed",
            "summary": "Code and focused tests match the design.",
            "evidence_paths": ["evidence.py"],
            "tests": ["pytest tests/example.py: passed"],
        },
        worktree=tmp_path,
        apply=False,
    )
    assert validated["evidence_paths"] == ["evidence.py"]

    with pytest.raises(RuntimeError, match="inside the repository"):
        agent.validate_result(
            {
                "outcome": "reviewed",
                "summary": "Invalid evidence.",
                "evidence_paths": ["../outside.py"],
                "tests": [],
            },
            worktree=tmp_path,
            apply=False,
        )


def test_prompt_separates_report_and_apply_authority() -> None:
    _load_module()
    agent = sys.modules["roadmap_verification_agent"]
    job = {
        "document": "docs/roadmap/example.md",
        "translation": "docs/roadmap/example-ko.md",
        "route_ids": ["example"],
        "validation_commands": ["pytest tests/example.py"],
    }

    report_prompt = agent.prompt(job, apply=False)
    apply_prompt = agent.prompt(job, apply=True)

    assert "Do not edit or commit any file" in report_prompt
    assert "Update and commit both document variants" in apply_prompt
    assert "confirm every evidence path exists exactly as written" in report_prompt
    assert "Never run repository-wide validation" in apply_prompt
    assert "code_verification_status: <outcome>" in apply_prompt


def test_worker_rejects_verification_surface_changes() -> None:
    module = _load_module()

    module._reject_verification_surface_changes(
        [
            "services/core-control-plane/src/fdai/core/example.py",
            "services/core-control-plane/tests/core/test_example.py",
        ]
    )
    with pytest.raises(RuntimeError, match="repository-control"):
        module._reject_verification_surface_changes(
            [
                "services/core-control-plane/src/fdai/core/example.py",
                "scripts/automation/tests-for-diff.sh",
            ]
        )


def test_worker_git_environment_disables_hooks_only_for_ephemeral_process(
    tmp_path: Path,
) -> None:
    _load_module()
    agent = sys.modules["roadmap_verification_agent"]

    environment = agent.worker_environment(tmp_path, tmp_path)

    assert environment["GIT_CONFIG_KEY_0"] == "core.hooksPath"
    assert environment["GIT_CONFIG_VALUE_0"] == "/dev/null"


def test_retry_failed_claims_only_failed_jobs() -> None:
    module = _load_module()

    assert module._eligible_statuses(apply=False, retry_failed=True) == frozenset({"failed"})
    assert module._eligible_statuses(apply=False, retry_failed=False) == frozenset(
        {"queued", "failed"}
    )


def _run(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - test-controlled commands and paths
        arguments,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _worker_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "docs/roadmap").mkdir(parents=True)
    (repo / "scripts/automation").mkdir(parents=True)
    (repo / "scripts/lib").mkdir(parents=True)
    (repo / "scripts/quality/localization").mkdir(parents=True)
    (repo / "docs/roadmap/example.md").write_text(
        "---\ntitle: Example\n---\n# Example\n",
        encoding="utf-8",
    )
    (repo / "docs/roadmap/example-ko.md").write_text(
        "---\ntitle: Example KO\ntranslation_of: example.md\n"
        "translation_source_sha: initial\n---\n# Example KO\n",
        encoding="utf-8",
    )
    (repo / "scripts/lib/design-routes.json").write_text(
        json.dumps(
            {
                "version": 1,
                "routes": [
                    {
                        "id": "baseline",
                        "paths": ["**"],
                        "must_read": [],
                        "validate": [],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    for filename in (
        "roadmap_verification.py",
        "roadmap_verification_agent.py",
        "roadmap_verification_inventory.py",
        "roadmap_verification_worker.py",
    ):
        shutil.copy2(AUTOMATION / filename, repo / "scripts/automation" / filename)
    (repo / "scripts/automation/tests-for-diff.sh").write_text(
        "#!/usr/bin/env bash\nexit 0\n",
        encoding="utf-8",
    )
    (repo / "scripts/quality/localization/check-translations.sh").write_text(
        "#!/usr/bin/env bash\nexit 0\n",
        encoding="utf-8",
    )
    assert _run(repo, "git", "init", "--quiet", "--initial-branch=main").returncode == 0
    assert _run(repo, "git", "config", "user.email", "user@example.com").returncode == 0
    assert _run(repo, "git", "config", "user.name", "Example User").returncode == 0
    assert _run(repo, "git", "add", ".").returncode == 0
    assert _run(repo, "git", "commit", "--quiet", "-m", "initial").returncode == 0
    return repo


def test_apply_worker_retains_verified_branch_and_receipt(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    repo = _worker_repo(tmp_path)
    fake = tmp_path / "fake-copilot"
    today = datetime.now(UTC).date().isoformat()
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, subprocess\n"
        f"today = {today!r}\n"
        "root = pathlib.Path.cwd()\n"
        "english = root / 'docs/roadmap/example.md'\n"
        "korean = root / 'docs/roadmap/example-ko.md'\n"
        "english.write_text(english.read_text().replace('title: Example\\n', "
        "f'title: Example\\ncode_verification_status: not_applicable\\n' "
        "+ f'code_verified_at: {today}\\n'))\n"
        "sha = subprocess.check_output(['git', 'hash-object', str(english)], text=True).strip()\n"
        "korean.write_text(korean.read_text().replace('title: Example KO\\n', "
        "f'title: Example KO\\ncode_verification_status: not_applicable\\n' "
        "+ f'code_verified_at: {today}\\n').replace('translation_source_sha: initial', "
        "f'translation_source_sha: {sha}'))\n"
        "subprocess.run(['git', 'add', 'docs/roadmap/example.md', "
        "'docs/roadmap/example-ko.md'], check=True)\n"
        "subprocess.run(['git', 'commit', '-m', 'docs(roadmap): verify example'], check=True)\n"
        "print(json.dumps({'outcome': 'not_applicable', 'summary': 'Index-only document.', "
        "'evidence_paths': [], 'tests': []}))\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("FDAI_COPILOT_CLI", str(fake))
    monkeypatch.setenv("FDAI_ROADMAP_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    paths = sys.modules["roadmap_verification"].queue_paths(repo)

    result = module.run_one(
        paths,
        apply=True,
        base_ref="HEAD",
        lease_seconds=60,
        timeout=30,
        integrate=True,
    )

    assert result is not None
    assert result["status"] == "not_applicable"
    receipt = json.loads((paths.receipts / f"{result['job_id']}.json").read_text(encoding="utf-8"))
    branch = receipt["result"]["branch"]
    assert branch == "main"
    assert "code_verification_status: not_applicable" in (
        repo / "docs/roadmap/example.md"
    ).read_text(encoding="utf-8")
    job_branches = _run(repo, "git", "branch", "--list", "roadmap-verification/*").stdout
    assert job_branches == ""
    assert not any((tmp_path / "worktrees").glob("*"))
    assert not (paths.state_root.parent / "fdai-validation-queue").exists()
