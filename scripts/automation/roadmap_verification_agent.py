"""Bounded Copilot execution for one roadmap verification worktree."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Final

MAX_OUTPUT_BYTES: Final = 200_000
MAX_SUMMARY_CHARS: Final = 2_000
UTC = timezone.utc  # noqa: UP017 - repository automation supports system Python 3.10.
RESULTS: Final = frozenset(
    {"reviewed", "verified", "gap_found", "designed", "not_applicable", "blocked"}
)
DENIED_TOOLS: Final = (
    "url",
    "shell(git push)",
    "shell(git reset)",
    "shell(git clean)",
    "shell(git restore)",
    "shell(az)",
    "shell(azd)",
    "shell(terraform)",
    "shell(kubectl)",
    "shell(curl)",
    "shell(wget)",
    "shell(ssh)",
)


def copilot_path() -> Path | None:
    configured = os.environ.get("FDAI_COPILOT_CLI", "").strip()
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path.home()
        / ".vscode-server/data/User/globalStorage/github.copilot-chat/copilotCli/copilot",
        Path(shutil.which("copilot") or "") if shutil.which("copilot") else None,
    ]
    return next(
        (candidate for candidate in candidates if candidate and candidate.is_file()),
        None,
    )


def worker_environment(repo_root: Path, worktree: Path) -> dict[str, str]:
    allowed = {
        "HOME",
        "USER",
        "LOGNAME",
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "SHELL",
        "TZ",
        "TERM",
        "TMPDIR",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "COPILOT_API_TOKEN",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment["PYTHONPATH"] = str(worktree / "src")
    primary_venv = repo_root / ".venv"
    if primary_venv.is_dir():
        environment["UV_PROJECT_ENVIRONMENT"] = str(primary_venv)
    environment.update(
        {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": "/dev/null",
        }
    )
    return environment


def _terminate(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except OSError:
            pass
        process.wait()


def copilot_command(cli: Path, prompt_text: str, worktree: Path, *, apply: bool) -> list[str]:
    tools = "read,glob,grep,shell,write" if apply else "read,glob,grep,shell"
    command = [
        str(cli),
        "-p",
        prompt_text,
        "--output-format",
        "text",
        "--add-dir",
        str(worktree),
        f"--available-tools={tools}",
        "--allow-all-tools",
        "--no-ask-user",
        "--no-auto-update",
        "--no-remote",
        "--no-remote-export",
        "--disable-builtin-mcps",
        "--no-color",
        "--silent",
    ]
    command.extend(f"--deny-tool={denied}" for denied in DENIED_TOOLS)
    if not apply:
        command.extend(("--deny-tool=shell(git add)", "--deny-tool=shell(git commit)"))
    return command


def run_copilot(
    cli: Path,
    prompt_text: str,
    worktree: Path,
    *,
    apply: bool,
    timeout: int,
    repo_root: Path,
) -> str:
    process = subprocess.Popen(  # noqa: S603 - fixed Copilot CLI and bounded options
        copilot_command(cli, prompt_text, worktree, apply=apply),
        cwd=worktree,
        env=worker_environment(repo_root, worktree),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate(process)
        raise RuntimeError("Copilot roadmap worker timed out") from exc
    output = ((stdout or "") + "\n" + (stderr or "")).strip()
    if process.returncode != 0:
        raise RuntimeError(f"Copilot roadmap worker exited with code {process.returncode}")
    if len(output.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise RuntimeError("Copilot roadmap worker output exceeded the byte cap")
    return output


def json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError("Copilot roadmap worker returned no JSON object")


def _safe_relative_path(value: object, *, worktree: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("evidence paths must be non-empty strings")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise RuntimeError("evidence paths must stay inside the repository")
    resolved = (worktree / candidate).resolve()
    if worktree.resolve() not in resolved.parents and resolved != worktree.resolve():
        raise RuntimeError("evidence paths must stay inside the repository")
    if not resolved.exists():
        raise RuntimeError(f"evidence path does not exist: {candidate}")
    return candidate.as_posix()


def validate_result(payload: dict[str, Any], *, worktree: Path, apply: bool) -> dict[str, Any]:
    outcome = payload.get("outcome")
    allowed = (
        {"verified", "designed", "not_applicable", "blocked"}
        if apply
        else {"reviewed", "gap_found", "designed", "not_applicable", "blocked"}
    )
    if outcome not in allowed or outcome not in RESULTS:
        raise RuntimeError(f"invalid roadmap worker outcome for this mode: {outcome}")
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_SUMMARY_CHARS:
        raise RuntimeError("roadmap worker summary is missing or too long")
    raw_evidence = payload.get("evidence_paths", [])
    raw_tests = payload.get("tests", [])
    if not isinstance(raw_evidence, list) or len(raw_evidence) > 40:
        raise RuntimeError("roadmap worker evidence_paths must be a bounded list")
    if not isinstance(raw_tests, list) or len(raw_tests) > 20:
        raise RuntimeError("roadmap worker tests must be a bounded list")
    evidence = [_safe_relative_path(value, worktree=worktree) for value in raw_evidence]
    tests = [value for value in raw_tests if isinstance(value, str) and 0 < len(value) <= 500]
    if len(tests) != len(raw_tests):
        raise RuntimeError("roadmap worker tests contain an invalid entry")
    if outcome in {"reviewed", "verified"} and (not evidence or not tests):
        raise RuntimeError("implemented outcomes require code evidence and focused test results")
    return {
        "outcome": outcome,
        "summary": " ".join(summary.split()),
        "evidence_paths": evidence,
        "tests": tests,
    }


def prompt(job: Mapping[str, Any], *, apply: bool) -> str:
    status_values = "verified|designed|not_applicable|blocked"
    mode_rules = (
        "Implement every verified gap and add focused tests. For aligned implementations use "
        "verified; for an explicitly future design with honestly absent code use designed; for "
        "an index or non-implementation document use not_applicable. Update and commit both "
        "document variants."
        if apply
        else "Do not edit or commit any file. Classify the document as reviewed, gap_found, "
        "designed, not_applicable, or blocked."
    )
    route_commands = "\n".join(f"- {command}" for command in job["validation_commands"])
    verification_date = datetime.now(UTC).date().isoformat()
    return f"""Audit one FDAI roadmap document against the current implementation.

Target English document: {job["document"]}
Target Korean document: {job["translation"]}
Matched design routes: {", ".join(job["route_ids"]) or "none"}
Candidate validation commands:
{route_commands or "- none; identify the narrowest focused check from adjacent tests"}

Rules:
- Read the target design, applicable repository instructions, implementing code, and adjacent tests.
- Break normative design statements into claims and require code plus focused-test evidence.
- Never infer implementation from filenames, imports, prose, or a passing unrelated test.
- Before returning, use glob or read to confirm every evidence path exists exactly as written.
- If design is ambiguous or would require an architecture decision, return blocked.
- Never run repository-wide validation, deployment, cloud, network, push, or destructive git.
- Do not modify repository instructions, hooks, automation, quality gates, or test configuration.
- Preserve customer-agnostic scope, safety invariants, and existing public contracts.
- {mode_rules}
- In apply mode, both documents need `code_verification_status: <outcome>` and
  `code_verified_at: {verification_date}` in YAML frontmatter. Refresh the Korean source SHA.
- End with exactly one JSON object and no prose after it:
{{"outcome":"{status_values if apply else "reviewed|gap_found|designed|not_applicable|blocked"}",
 "summary":"bounded factual result","evidence_paths":["relative/path"],
 "tests":["focused command and result"]}}
"""
