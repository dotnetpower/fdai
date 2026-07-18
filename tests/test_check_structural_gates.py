"""Behavioral tests for the three structural CI gates.

Covers the file LOC, agent import, and subsystem fan-out checks under
``scripts/quality/architecture/``. Each script is driven against a
throwaway workspace layout so warn-vs-enforce mode, threshold overrides,
allowlist handling, and the fail-loud path are all pinned against regression.

Tracker: issue #14, gate PR: issue #22.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GATE_DIR = _REPO_ROOT / "scripts" / "quality" / "architecture"
_FILE_LOC = _GATE_DIR / "check-file-loc.sh"
_AGENTS = _GATE_DIR / "check-agents-imports.sh"
_FANOUT = _GATE_DIR / "check-subsystem-fanout.sh"
_GIT = shutil.which("git") or "git"
_BASH = shutil.which("bash") or "bash"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed argv, whitelisted binary
        [_GIT, *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "gate-tests@example.com")
    _git(repo, "config", "user.name", "gate-tests")
    return repo


def _copy_scripts(repo: Path) -> None:
    (repo / "scripts").mkdir()
    for src in (_FILE_LOC, _AGENTS, _FANOUT):
        dst = repo / "scripts" / src.name
        dst.write_text(src.read_text())
        dst.chmod(0o755)


def _run(repo: Path, script: Path, **env_extra: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    # Neutralize any inherited mode signals so each test controls its own env.
    for key in (
        "FILE_LOC_MODE",
        "FILE_LOC_WARN",
        "FILE_LOC_FAIL",
        "SUBSYSTEM_FANOUT_MODE",
        "SUBSYSTEM_FANOUT_WARN",
        "SUBSYSTEM_FANOUT_FAIL",
        "CHECK_QUIET",
    ):
        env.pop(key, None)
    env.update(env_extra)
    return subprocess.run(  # noqa: S603 - fixed argv, whitelisted binary
        [_BASH, str(script)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# check-file-loc.sh
# ---------------------------------------------------------------------------


def _seed_python_file(repo: Path, rel: str, lines: int) -> Path:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"x = {i}" for i in range(lines)) + "\n"
    path.write_text(body)
    return path


class TestCheckFileLoc:
    def test_empty_tree_passes(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        (repo / "src" / "fdai").mkdir(parents=True)
        result = _run(repo, repo / "scripts" / "check-file-loc.sh")
        assert result.returncode == 0, result.stderr
        assert "skipping" in result.stdout

    def test_warn_mode_never_fails(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        _seed_python_file(repo, "src/fdai/tiny.py", 10)
        _seed_python_file(repo, "src/fdai/mid.py", 500)  # > 400 warn
        _seed_python_file(repo, "src/fdai/huge.py", 900)  # > 800 fail
        result = _run(repo, repo / "scripts" / "check-file-loc.sh")
        assert result.returncode == 0
        assert "warned=1" in result.stdout
        assert "failed=1" in result.stdout
        assert "mode=warn" in result.stdout

    def test_enforce_mode_fails_on_over_800(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        _seed_python_file(repo, "src/fdai/huge.py", 900)
        result = _run(repo, repo / "scripts" / "check-file-loc.sh", FILE_LOC_MODE="enforce")
        assert result.returncode == 1
        assert "failed=1" in result.stdout

    def test_enforce_mode_passes_without_fails(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        _seed_python_file(repo, "src/fdai/mid.py", 500)  # only warn
        result = _run(repo, repo / "scripts" / "check-file-loc.sh", FILE_LOC_MODE="enforce")
        assert result.returncode == 0
        assert "failed=0" in result.stdout

    def test_thresholds_are_env_overridable(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        _seed_python_file(repo, "src/fdai/mid.py", 500)
        result = _run(
            repo,
            repo / "scripts" / "check-file-loc.sh",
            FILE_LOC_MODE="enforce",
            FILE_LOC_WARN="100",
            FILE_LOC_FAIL="300",
        )
        assert result.returncode == 1
        assert "failed=1" in result.stdout

    def test_invalid_threshold_ordering_rejected(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        result = _run(
            repo,
            repo / "scripts" / "check-file-loc.sh",
            FILE_LOC_WARN="800",
            FILE_LOC_FAIL="400",  # inverted
        )
        assert result.returncode == 2
        assert "must be <" in result.stderr

    def test_non_integer_threshold_rejected(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        result = _run(
            repo,
            repo / "scripts" / "check-file-loc.sh",
            FILE_LOC_WARN="lots",
        )
        assert result.returncode == 2
        assert "must be integers" in result.stderr

    def test_allowlist_skips_files(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        _seed_python_file(repo, "src/fdai/huge.py", 900)
        (repo / "scripts" / ".check-file-loc.allowlist").write_text(
            "# huge.py: intentionally big during migration\nsrc/fdai/huge.py\n"
        )
        result = _run(repo, repo / "scripts" / "check-file-loc.sh", FILE_LOC_MODE="enforce")
        assert result.returncode == 0
        assert "allowlisted=1" in result.stdout

    def test_allowlist_entry_without_justification_rejected(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        _seed_python_file(repo, "src/fdai/huge.py", 900)
        # No '#' comment preceding the entry - a governance smell.
        (repo / "scripts" / ".check-file-loc.allowlist").write_text("src/fdai/huge.py\n")
        result = _run(repo, repo / "scripts" / "check-file-loc.sh")
        assert result.returncode == 2
        assert "justification comment" in result.stderr

    def test_allowlist_glob_pattern_matches(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        _seed_python_file(repo, "src/fdai/generated/a.py", 900)
        _seed_python_file(repo, "src/fdai/generated/b.py", 950)
        _seed_python_file(repo, "src/fdai/handwritten.py", 900)
        (repo / "scripts" / ".check-file-loc.allowlist").write_text(
            "# generated: tolerated pending code-gen split\nsrc/fdai/generated/*.py\n"
        )
        result = _run(repo, repo / "scripts" / "check-file-loc.sh", FILE_LOC_MODE="enforce")
        assert result.returncode == 1  # handwritten still fails
        assert "allowlisted=2" in result.stdout
        assert "failed=1" in result.stdout

    def test_stale_allowlist_entry_fails_enforce(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        _seed_python_file(repo, "src/fdai/small.py", 10)  # under warn
        (repo / "scripts" / ".check-file-loc.allowlist").write_text(
            "# ghost: file was refactored away but exemption forgotten\nsrc/fdai/ghost.py\n"
        )
        # Enforce: stale entry is a failure.
        result = _run(repo, repo / "scripts" / "check-file-loc.sh", FILE_LOC_MODE="enforce")
        assert result.returncode == 1
        assert "stale allowlist entry" in result.stdout

    def test_stale_allowlist_entry_warns_in_warn_mode(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        _seed_python_file(repo, "src/fdai/small.py", 10)
        (repo / "scripts" / ".check-file-loc.allowlist").write_text(
            "# ghost: file was refactored away but exemption forgotten\nsrc/fdai/ghost.py\n"
        )
        # Warn mode: still exit 0, but the stale line is surfaced.
        result = _run(repo, repo / "scripts" / "check-file-loc.sh")
        assert result.returncode == 0
        assert "stale allowlist entry" in result.stdout

    def test_quiet_mode_suppresses_per_file_lines(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        for i in range(5):
            _seed_python_file(repo, f"src/fdai/m{i}.py", 500)
        result = _run(repo, repo / "scripts" / "check-file-loc.sh", CHECK_QUIET="1")
        assert result.returncode == 0
        assert "warned=5" in result.stdout
        # Per-file lines should not be present.
        assert "check-file-loc: warn " not in result.stdout
        # GitHub annotations still emitted (CI needs them).
        assert "::notice file=" in result.stdout

    def test_pycache_is_excluded(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        _seed_python_file(repo, "src/fdai/__pycache__/junk.py", 5000)
        # Add a normal file so the "no python files" skip path is not taken;
        # otherwise the test cannot distinguish exclusion from empty tree.
        _seed_python_file(repo, "src/fdai/keeper.py", 5)
        result = _run(repo, repo / "scripts" / "check-file-loc.sh")
        assert result.returncode == 0
        assert "scanned=1" in result.stdout  # only keeper.py, __pycache__ skipped

    @pytest.mark.parametrize(
        "lines,expected_bucket",
        [
            (400, "clean"),  # exactly at warn threshold - not exceeded
            (401, "warn"),  # one over -> warn
            (800, "warn"),  # exactly at fail threshold - not exceeded
            (801, "fail"),  # one over -> fail
        ],
    )
    def test_threshold_boundary_conditions(
        self, tmp_path: Path, lines: int, expected_bucket: str
    ) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        _seed_python_file(repo, "src/fdai/edge.py", lines)
        result = _run(repo, repo / "scripts" / "check-file-loc.sh")
        assert result.returncode == 0  # warn mode is never fatal
        if expected_bucket == "clean":
            assert "warned=0" in result.stdout
            assert "failed=0" in result.stdout
        elif expected_bucket == "warn":
            assert "warned=1" in result.stdout
            assert "failed=0" in result.stdout
        elif expected_bucket == "fail":
            assert "warned=0" in result.stdout
            assert "failed=1" in result.stdout


# ---------------------------------------------------------------------------
# check-agents-imports.sh
# ---------------------------------------------------------------------------


class TestCheckAgentsImports:
    def test_missing_agents_dir_passes(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        result = _run(repo, repo / "scripts" / "check-agents-imports.sh")
        assert result.returncode == 0
        assert "absent" in result.stdout

    def test_clean_agent_passes(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        (repo / "src" / "fdai" / "agents").mkdir(parents=True)
        (repo / "src" / "fdai" / "agents" / "odin.py").write_text(
            "from fdai.core.executor import ShadowExecutor\n"
            "from fdai.shared.contracts.models import Verdict\n"
        )
        result = _run(repo, repo / "scripts" / "check-agents-imports.sh")
        assert result.returncode == 0
        assert "OK" in result.stdout

    @pytest.mark.parametrize(
        "banned_line",
        [
            "import httpx\n",
            "import requests\n",
            "import aiohttp\n",
            "import boto3\n",
            "import azure.identity\n",
            "from azure.identity import DefaultAzureCredential\n",
            "from google.cloud import storage\n",
            "from fdai.delivery.azure import arg_query\n",
        ],
    )
    def test_forbidden_imports_are_flagged(self, tmp_path: Path, banned_line: str) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        (repo / "src" / "fdai" / "agents").mkdir(parents=True)
        (repo / "src" / "fdai" / "agents" / "loki.py").write_text(banned_line)
        result = _run(repo, repo / "scripts" / "check-agents-imports.sh")
        assert result.returncode == 1
        assert "forbidden import" in result.stdout

    def test_framework_subdir_is_also_scanned(self, tmp_path: Path) -> None:
        # G-7 will introduce agents/_framework/; ensure it is not missed.
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        (repo / "src" / "fdai" / "agents" / "_framework").mkdir(parents=True)
        (repo / "src" / "fdai" / "agents" / "_framework" / "bus.py").write_text("import httpx\n")
        result = _run(repo, repo / "scripts" / "check-agents-imports.sh")
        assert result.returncode == 1

    def test_allowlist_glob_pattern_matches(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        (repo / "src" / "fdai" / "agents" / "_framework").mkdir(parents=True)
        # A tolerated legacy file whose import we cannot fix this PR.
        (repo / "src" / "fdai" / "agents" / "_framework" / "legacy.py").write_text("import httpx\n")
        (repo / "scripts" / ".check-agents-imports.allowlist").write_text(
            "# legacy: transport call queued for extraction in follow-up PR\n"
            "src/fdai/agents/_framework/legacy.py\n"
        )
        result = _run(repo, repo / "scripts" / "check-agents-imports.sh")
        assert result.returncode == 0
        assert "allowlisted=1" in result.stdout

    def test_stale_allowlist_entry_fails(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        (repo / "src" / "fdai" / "agents").mkdir(parents=True)
        (repo / "src" / "fdai" / "agents" / "odin.py").write_text("import os\n")
        (repo / "scripts" / ".check-agents-imports.allowlist").write_text(
            "# ghost: cleanup left this behind\nsrc/fdai/agents/_framework/gone.py\n"
        )
        result = _run(repo, repo / "scripts" / "check-agents-imports.sh")
        assert result.returncode == 1
        assert "stale allowlist entry" in result.stdout


# ---------------------------------------------------------------------------
# check-subsystem-fanout.sh
# ---------------------------------------------------------------------------


class TestCheckSubsystemFanout:
    def test_missing_core_dir_passes(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        result = _run(repo, repo / "scripts" / "check-subsystem-fanout.sh")
        assert result.returncode == 0

    def test_low_fanout_is_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        core = repo / "src" / "fdai" / "core"
        core.mkdir(parents=True)
        (core / "small.py").write_text(
            "from fdai.core.executor import ShadowExecutor\nfrom fdai.core.audit import AuditLog\n"
        )
        result = _run(repo, repo / "scripts" / "check-subsystem-fanout.sh")
        assert result.returncode == 0
        assert "warned=0" in result.stdout

    def test_warn_threshold_flags_but_passes(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        core = repo / "src" / "fdai" / "core"
        core.mkdir(parents=True)
        body = "".join(f"from fdai.core.sub{i} import Foo\n" for i in range(9))
        (core / "medium.py").write_text(body)
        result = _run(repo, repo / "scripts" / "check-subsystem-fanout.sh")
        assert result.returncode == 0
        assert "warned=1" in result.stdout

    def test_enforce_mode_fails_over_15(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        core = repo / "src" / "fdai" / "core"
        core.mkdir(parents=True)
        body = "".join(f"from fdai.core.sub{i} import Foo\n" for i in range(16))
        (core / "godlike.py").write_text(body)
        result = _run(
            repo,
            repo / "scripts" / "check-subsystem-fanout.sh",
            SUBSYSTEM_FANOUT_MODE="enforce",
        )
        assert result.returncode == 1

    def test_own_subsystem_is_not_counted(self, tmp_path: Path) -> None:
        # Files under core/foo/ importing from core.foo.* must not count
        # their own subsystem against the fan-out budget.
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        pkg = repo / "src" / "fdai" / "core" / "foo"
        pkg.mkdir(parents=True)
        body = "".join(f"from fdai.core.foo.sub{i} import Foo\n" for i in range(20))
        body += "from fdai.core.audit import x\n"  # only 1 other subsystem
        (pkg / "impl.py").write_text(body)
        result = _run(
            repo,
            repo / "scripts" / "check-subsystem-fanout.sh",
            SUBSYSTEM_FANOUT_MODE="enforce",
        )
        assert result.returncode == 0

    def test_allowlist_skips_files(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        core = repo / "src" / "fdai" / "core"
        core.mkdir(parents=True)
        body = "".join(f"from fdai.core.sub{i} import Foo\n" for i in range(16))
        (core / "orchestrator.py").write_text(body)
        (repo / "scripts" / ".check-subsystem-fanout.allowlist").write_text(
            "# orchestrator: legitimate composition root; wires stages\n"
            "src/fdai/core/orchestrator.py\n"
        )
        result = _run(
            repo,
            repo / "scripts" / "check-subsystem-fanout.sh",
            SUBSYSTEM_FANOUT_MODE="enforce",
        )
        assert result.returncode == 0
        assert "allowlisted=1" in result.stdout

    @pytest.mark.parametrize(
        "count,expected_bucket",
        [
            (7, "clean"),  # just below warn
            (8, "warn"),  # exactly at warn threshold - triggers warn
            (14, "warn"),  # just below fail
            (15, "fail"),  # exactly at fail threshold - triggers fail
        ],
    )
    def test_fanout_boundary_conditions(
        self, tmp_path: Path, count: int, expected_bucket: str
    ) -> None:
        repo = _make_repo(tmp_path)
        _copy_scripts(repo)
        core = repo / "src" / "fdai" / "core"
        core.mkdir(parents=True)
        body = "".join(f"from fdai.core.sub{i} import Foo\n" for i in range(count))
        (core / "edge.py").write_text(body)
        result = _run(repo, repo / "scripts" / "check-subsystem-fanout.sh")
        assert result.returncode == 0  # warn mode is never fatal
        if expected_bucket == "clean":
            assert "warned=0" in result.stdout
            assert "failed=0" in result.stdout
        elif expected_bucket == "warn":
            assert "warned=1" in result.stdout
            assert "failed=0" in result.stdout
        elif expected_bucket == "fail":
            assert "warned=0" in result.stdout
            assert "failed=1" in result.stdout


# ---------------------------------------------------------------------------
# Drift guard: repo-level baseline
# ---------------------------------------------------------------------------


def test_repo_baseline_warn_only_holds() -> None:
    """The three scripts ship warn-only; the live repo must pass all three."""
    for script in (_FILE_LOC, _AGENTS, _FANOUT):
        result = subprocess.run(  # noqa: S603 - fixed argv, whitelisted binary
            [_BASH, str(script)],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"{script.name} regressed under warn-only baseline\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
